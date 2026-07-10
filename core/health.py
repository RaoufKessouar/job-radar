"""Surveillance des canaux : alerte email si un canal ne remonte plus rien.

Règle : alerte si un canal renvoie 0 offre pendant plus de N heures OUVRÉES
(les samedis/dimanches ne comptent pas — personne ne publie le week-end).
Une seule alerte par panne (drapeau), plus un email de rétablissement.

L'état vit dans state.json sous la clé "_health" (préservée par la purge).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone


def _heures_ouvrees_ecoulees(depuis_ts: float) -> float:
    """Heures écoulées entre depuis_ts et maintenant, hors samedi/dimanche."""
    start = datetime.fromtimestamp(depuis_ts, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    if start >= now:
        return 0.0
    total = 0.0
    cur = start
    while cur < now:
        step = min(cur + timedelta(hours=1), now)
        if cur.weekday() < 5:  # 0-4 = lundi-vendredi
            total += (step - cur).total_seconds() / 3600
        cur = step
    return total


def check(state: dict, canal: str, nb_offres: int, cfg: dict, send_alert) -> None:
    """À appeler après chaque scan d'un canal.

    send_alert(subject, text) : fonction d'envoi d'email.
    """
    seuil_h = cfg.get("sante", {}).get("seuil_heures_ouvrees", 48)
    health = state.setdefault("_health", {})
    h = health.setdefault(canal, {"last_success": time.time(), "alerted": False})

    if nb_offres > 0:
        if h.get("alerted"):
            send_alert(f"✅ Stage Radar: canal {canal} rétabli",
                       f"Le canal {canal} remonte à nouveau des offres "
                       f"({nb_offres} à ce run).")
        h["last_success"] = time.time()
        h["alerted"] = False
        return

    ecoulees = _heures_ouvrees_ecoulees(h.get("last_success", time.time()))
    if ecoulees > seuil_h and not h.get("alerted"):
        send_alert(
            f"⚠️ Stage Radar: canal {canal} silencieux depuis {ecoulees:.0f}h ouvrées",
            f"Le canal {canal} n'a remonté aucune offre depuis plus de "
            f"{seuil_h}h ouvrées (week-ends exclus).\n\n"
            f"Causes possibles : changement d'API du site, filtre cassé, "
            f"blocage des IPs GitHub.\n"
            f"Regarde les logs du workflow: "
            f"https://github.com/RaoufKessouar/job-radar/actions",
        )
        h["alerted"] = True
