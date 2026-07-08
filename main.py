#!/usr/bin/env python3
"""Stage Radar — détection d'offres de stage (WTTJ + LinkedIn) + notification email.

Usage :
  python main.py                 # run normal (scrape + score + email)
  python main.py --dry-run       # scrape + score, affiche les emails sans les envoyer
  python main.py --sample        # test hors-ligne complet avec des offres factices
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from scrapers import wttj, linkedin  # noqa: E402
from core import dedup, scoring      # noqa: E402
from notify import emailer           # noqa: E402

ROOT = Path(__file__).parent
STATE_FILE = ROOT / "state.json"

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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="n'envoie pas d'emails")
    parser.add_argument("--sample", action="store_true", help="test hors-ligne avec offres factices")
    args = parser.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

    # 1. Collecte
    if args.sample:
        offers = list(SAMPLE_OFFERS)
        print(f"[main] mode sample: {len(offers)} offres factices")
    else:
        offers = wttj.search(cfg) + linkedin.search(cfg)
        print(f"[main] {len(offers)} offres collectées au total")

    # 2. Déduplication
    state = dedup.load_state(STATE_FILE)
    new_offers = dedup.filter_new(offers, state)
    print(f"[main] {len(new_offers)} nouvelles offres (jamais vues)")

    # 3. Scoring
    relevant = scoring.rank(new_offers, cfg)
    print(f"[main] {len(relevant)} offres au-dessus du seuil de pertinence")
    for o in relevant:
        print(f"    [{o['score']:3d}] {o['title'][:70]} — {o['company']} ({o['source']})")

    # 4. Notification
    emailer.notify(relevant, cfg, dry_run=args.dry_run or args.sample)

    # 5. Persistance de l'état (aussi pour les offres sous le seuil : vues = vues)
    dedup.save_state(state, STATE_FILE)
    print("[main] state.json mis à jour")
    return 0


if __name__ == "__main__":
    sys.exit(main())
