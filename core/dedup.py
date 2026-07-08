"""Déduplication : ne jamais notifier deux fois la même offre.

L'état est stocké dans state.json (commité par le workflow GitHub Actions
après chaque run, ce qui sert aussi d'historique gratuit).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

RETENTION_JOURS = 60


def _normalize(s: str) -> str:
    return re.sub(r"\W+", "", s.lower())


def offer_key(offer: dict) -> str:
    """Hash stable titre+entreprise (résiste aux republis avec URL différente)."""
    raw = _normalize(offer.get("title", "")) + "|" + _normalize(offer.get("company", ""))
    return hashlib.md5(raw.encode()).hexdigest()


def load_state(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_state(state: dict, path: str | Path) -> None:
    # Purge des entrées trop vieilles
    cutoff = time.time() - RETENTION_JOURS * 86400
    state = {k: v for k, v in state.items() if v.get("first_seen", 0) > cutoff}
    Path(path).write_text(
        json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def filter_new(offers: list[dict], state: dict) -> list[dict]:
    """Retourne les offres jamais vues et les enregistre dans l'état."""
    new = []
    for offer in offers:
        key = offer_key(offer)
        if key in state:
            continue
        state[key] = {
            "first_seen": time.time(),
            "title": offer.get("title", "")[:120],
            "company": offer.get("company", "")[:80],
            "source": offer.get("source", ""),
        }
        new.append(offer)
    return new
