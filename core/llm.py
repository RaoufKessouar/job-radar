"""Jugement de pertinence des offres par Gemini.

- Appelle l'API REST Gemini (pas de SDK nécessaire), par LOTS d'offres
  pour économiser le quota.
- Plafond d'appels par run (garde-fou budget) : au-delà, les offres gardent
  leur score mots-clés et sont marquées non jugées.
- Si l'API échoue (panne, clé absente), fallback silencieux sur le score
  mots-clés : le radar ne s'arrête jamais.

Secret attendu : GEMINI_API_KEY (variable d'environnement).
"""

from __future__ import annotations

import json
import os
import time

import requests

API_URL = ("https://generativelanguage.googleapis.com/v1beta/models/"
           "{model}:generateContent?key={key}")

PROMPT_TEMPLATE = """Tu évalues des offres d'emploi pour un candidat.

PROFIL DU CANDIDAT :
{profil}

Pour CHAQUE offre ci-dessous, donne un score de pertinence de 0 à 100
(100 = correspond parfaitement au profil, 0 = hors sujet) et une raison
en une phrase courte en français.

Réponds UNIQUEMENT avec un tableau JSON de la forme :
[{{"i": <numéro de l'offre>, "score": <0-100>, "raison": "<phrase>"}}, ...]

OFFRES :
{offres}"""


def _format_offer(i: int, o: dict) -> str:
    desc = (o.get("description") or "")[:1200]
    return (f"--- Offre {i} ---\n"
            f"Titre: {o.get('title','')}\n"
            f"Entreprise: {o.get('company','')} | Lieu: {o.get('location','')}\n"
            f"Description: {desc if desc.strip() else '(non disponible)'}")


def _call_gemini(model: str, key: str, prompt: str) -> list[dict]:
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    r = requests.post(API_URL.format(model=model, key=key), json=body, timeout=60)
    r.raise_for_status()
    text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    data = json.loads(text)
    if not isinstance(data, list):
        raise ValueError("réponse LLM inattendue (pas un tableau JSON)")
    return data


def judge(offers: list[dict], cfg: dict) -> None:
    """Attache offer['score'] (et 'llm_raison') à chaque offre.

    Prérequis : offer['score_kw'] déjà calculé (fallback).
    """
    llm_cfg = cfg.get("llm", {})
    for o in offers:
        o["score"] = o.get("score_kw", 0)  # défaut = fallback

    if not llm_cfg.get("actif", False) or not offers:
        return
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("[llm] GEMINI_API_KEY absent — fallback scoring mots-clés")
        return

    model = llm_cfg.get("modele", "gemini-2.5-flash")
    lot = int(llm_cfg.get("lot", 10))
    cap = int(llm_cfg.get("max_offres_par_run", 40))
    profil = llm_cfg.get("profil", "")

    a_juger = offers[:cap]
    if len(offers) > cap:
        print(f"[llm] plafond atteint: {len(offers) - cap} offre(s) resteront "
              f"au score mots-clés")

    juged = 0
    for start in range(0, len(a_juger), lot):
        batch = a_juger[start:start + lot]
        offres_txt = "\n".join(_format_offer(i, o) for i, o in enumerate(batch))
        prompt = PROMPT_TEMPLATE.format(profil=profil, offres=offres_txt)
        try:
            results = _call_gemini(model, key, prompt)
        except (requests.RequestException, ValueError, KeyError,
                json.JSONDecodeError) as e:
            print(f"[llm] lot {start//lot + 1} échoué ({e}) — fallback mots-clés "
                  f"pour ces {len(batch)} offres")
            continue
        for item in results:
            try:
                idx = int(item["i"])
                if 0 <= idx < len(batch):
                    batch[idx]["score"] = max(0, min(100, int(item["score"])))
                    batch[idx]["llm_raison"] = str(item.get("raison", ""))[:200]
                    juged += 1
            except (KeyError, TypeError, ValueError):
                continue
        time.sleep(1)

    print(f"[llm] {juged}/{len(a_juger)} offres jugées par {model}")
