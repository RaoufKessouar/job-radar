#!/usr/bin/env python3
"""Test isolé des scrapers de sites carrières — AUCUN email, AUCUN état modifié.

Usage :  python test_carrieres.py
Affiche ce que chaque site remonte (titres, lieux, dates, URLs) pour
vérification à l'œil avant le branchement en production.
"""

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from scrapers import carrieres  # noqa: E402

cfg = yaml.safe_load((Path(__file__).parent / "config.yaml").read_text(encoding="utf-8"))
cfg.setdefault("carrieres", {})["actif"] = True

offers, fetch_ok = carrieres.search(cfg)

print()
print("=" * 78)
print(f"BILAN : {len(offers)} offres | statut requêtes : {fetch_ok}")
print("=" * 78)
for o in offers:
    print(f"\n[{o['source']}] {o['title']}")
    print(f"   lieu: {o['location'] or '(vide)'} | publiée: {o['date_posted'] or '(vide)'}")
    print(f"   url : {o['url']}")

print()
print("--- test détail sur les 2 premières offres ---")
sample = offers[:2]
carrieres.enrich_descriptions(sample, cfg)
for o in sample:
    print(f"\n[{o['source']}] {o['title']}")
    print(f"   description ({len(o.get('description',''))} car.): "
          f"{o.get('description','')[:300]}...")
