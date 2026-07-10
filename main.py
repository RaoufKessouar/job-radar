#!/usr/bin/env python3
"""Stage Radar — détection d'offres de stage (WTTJ + LinkedIn) + notification email.

Usage :
  python main.py                 # run normal (scrape + score + email)
  python main.py --dry-run       # scrape + score, affiche les emails sans les envoyer
  python main.py --sample        # test hors-ligne complet avec des offres factices
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from scrapers import wttj, linkedin  # noqa: E402
from core import dedup, scoring, llm, health  # noqa: E402
from notify import emailer           # noqa: E402

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "state.json"
HISTORY_FILE = ROOT / "historique.csv"

SAMPLE_OFFERS = [
    {"source": "sample", "title": "STAGE 2026 - IA / NLP - Gestion d'incertitude agents IA - F/H",
     "company": "Berger-Levrault", "location": "Labège", "url": "https://example.com/1",
     "date_posted": "2026-07-08",
     "description": "Master 2, LLM, NLP, self-consistency, Python, LangChain, stage 6 mois"},
    {"source": "sample", "title": "Stage - Ingénieur IA - F/H", "company": "Mobsuccess",
     "location": "Paris", "url": "https://example.com/2", "date_posted": "2026-07-08",
     "description": "IA générative, machine learning, fullstack, Python, école d'ingénieurs"},
    {"source": "sample", "title": "Alternance - Data Analyst", "company": "ACME",
     "location": "Paris", "url": "https://example.com/3", "date_posted": "2026-07-08",
     "description": "alternance 12 mois, SQL, Excel"},
    {"source": "sample", "title": "Ingénieur Machine Learning Senior (CDI)", "company": "BigCorp",
     "location": "Paris", "url": "https://example.com/4", "date_posted": "2026-07-08",
     "description": "5 ans d'expérience, deep learning, PyTorch"},
    {"source": "sample", "title": "Stage de pré-thèse - Computer Vision - IA générative",
     "company": "IDEMIA", "location": "Osny", "url": "https://example.com/5",
     "date_posted": "2026-07-08",
     "description": "M2 deep learning computer vision, PyTorch, NeRF, Python, 6 mois"},
]


def append_history(offers: list[dict]) -> None:
    """Base de données des offres détectées (une ligne par offre, avec score)."""
    if not offers:
        return
    is_new = not HISTORY_FILE.exists()
    with HISTORY_FILE.open("a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(["detecte_le", "score", "titre", "entreprise",
                             "ville", "source", "publiee_le", "url"])
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
        for o in offers:
            writer.writerow([now, o.get("score", ""), o.get("title", ""),
                             o.get("company", ""), o.get("location", ""),
                             o.get("source", ""), o.get("date_posted", ""),
                             o.get("url", "")])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="n'envoie pas d'emails")
    parser.add_argument("--sample", action="store_true", help="test hors-ligne avec offres factices")
    args = parser.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

    # 1. Collecte (+ surveillance santé de chaque canal)
    state = dedup.load_state(STATE_FILE)
    if args.sample:
        offers = list(SAMPLE_OFFERS)
        print(f"[main] mode sample: {len(offers)} offres factices")
    else:
        wttj_offers = wttj.search(cfg)
        li_offers = linkedin.search(cfg)
        health.check(state, "wttj", len(wttj_offers), cfg, emailer.send_alert)
        health.check(state, "linkedin", len(li_offers), cfg, emailer.send_alert)
        offers = wttj_offers + li_offers
        print(f"[main] {len(offers)} offres collectées au total")

    # 2. Déduplication
    new_offers = dedup.filter_new(offers, state)
    print(f"[main] {len(new_offers)} nouvelles offres (jamais vues)")

    # 3. Pré-filtre mots-clés (gratuit) : élimine l'évident hors-sujet
    for o in new_offers:
        o["score_kw"] = scoring.score(o, cfg)
    candidates = [o for o in new_offers if o["score_kw"] > 0]
    print(f"[main] {len(candidates)} candidates après pré-filtre mots-clés")

    # 4. Descriptions LinkedIn manquantes (2e passe, plafonnée)
    if not args.sample:
        linkedin.enrich_descriptions(candidates, cfg)

    # 5. Jugement Gemini (plafonné, fallback mots-clés intégré)
    llm.judge(candidates, cfg)
    for o in new_offers:
        o.setdefault("score", 0)

    threshold = cfg.get("scoring", {}).get("seuil_notification", 30)
    relevant = sorted([o for o in candidates if o["score"] >= threshold],
                      key=lambda o: o["score"], reverse=True)
    print(f"[main] {len(relevant)} offres au-dessus du seuil ({threshold})")
    for o in relevant:
        raison = f" | {o['llm_raison'][:60]}" if o.get("llm_raison") else ""
        print(f"    [{o['score']:3d}] {o['title'][:60]} — {o['company'][:25]} ({o['source']}){raison}")

    # 4. Historique CSV (toutes les nouvelles offres, même sous le seuil — utile pour régler le scoring)
    append_history(new_offers)

    # 5. Notification
    emailer.notify(relevant, cfg, dry_run=args.dry_run or args.sample)

    # 6. Persistance de l'état (aussi pour les offres sous le seuil : vues = vues)
    dedup.save_state(state, STATE_FILE)
    print("[main] state.json mis à jour")
    return 0


if __name__ == "__main__":
    sys.exit(main())
