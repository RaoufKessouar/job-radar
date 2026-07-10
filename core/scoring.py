"""Scoring de pertinence 0-100 basé sur les mots-clés du config.yaml.

Règles :
- le titre doit contenir un mot "obligatoire" (stage/intern/trainee), sinon score 0 ;
- un mot d'exclusion dans le titre annule l'offre, SAUF si le titre contient
  aussi "stage" (beaucoup d'offres sont étiquetées "Stage / Alternance") ;
- chaque mot-clé bonus rapporte son poids (x2 s'il est dans le titre) ;
- le score est plafonné à 100.
"""

from __future__ import annotations

import re


def _contains(text: str, kw: str) -> bool:
    """Mots courts (<=3 lettres, ex. 'ia', 'ai', 'ml', 'cv') : correspondance
    en mot entier pour éviter les faux positifs ('aix', 'mlops'...)."""
    if len(kw) <= 3:
        return re.search(rf"(?<![a-zà-ÿ0-9]){re.escape(kw)}(?![a-zà-ÿ0-9])", text) is not None
    return kw in text


def passes_gate(offer: dict, cfg: dict) -> bool:
    """Règles DURES uniquement (pré-filtre avant LLM) :
    le titre doit ressembler à un stage, et ne pas être une exclusion évidente.
    Aucune exigence de mot-clé thématique — c'est le LLM qui juge le fond."""
    s_cfg = cfg.get("scoring", {})
    title = (offer.get("title") or "").lower()
    if not any(w in title for w in s_cfg.get("obligatoires_titre", [])):
        return False
    has_stage = "stage" in title or "intern" in title
    for w in s_cfg.get("exclusions_titre", []):
        if w in title and not has_stage:
            return False
    return True


def score(offer: dict, cfg: dict) -> int:
    s_cfg = cfg.get("scoring", {})
    title = (offer.get("title") or "").lower()
    desc = (offer.get("description") or "").lower()
    text = title + " " + desc

    if not any(w in title for w in s_cfg.get("obligatoires_titre", [])):
        return 0

    has_stage = "stage" in title or "intern" in title
    for w in s_cfg.get("exclusions_titre", []):
        if w in title and not has_stage:
            return 0

    total = 0
    for kw, weight in s_cfg.get("bonus", {}).items():
        kw = kw.lower()
        if _contains(title, kw):
            total += weight * 2
        elif _contains(text, kw):
            total += weight

    return min(total, 100)


def rank(offers: list[dict], cfg: dict) -> list[dict]:
    """Attache offer['score'] et retourne les offres au-dessus du seuil, triées."""
    threshold = cfg.get("scoring", {}).get("seuil_notification", 30)
    kept = []
    for offer in offers:
        offer["score"] = score(offer, cfg)
        if offer["score"] >= threshold:
            kept.append(offer)
    return sorted(kept, key=lambda o: o["score"], reverse=True)
