"""Notification email via SMTP Gmail.

Secrets attendus en variables d'environnement (jamais dans le code) :
  SMTP_USER     : adresse Gmail expéditrice
  SMTP_PASSWORD : mot de passe d'application Gmail (PAS le mot de passe du compte)
  NOTIFY_TO     : destinataire (peut être la même adresse)
"""

from __future__ import annotations

import os
import smtplib
import sys
from email.mime.text import MIMEText
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import signals  # noqa: E402


def _send(subject: str, html: str) -> bool:
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD")
    to = os.environ.get("NOTIFY_TO", user)
    if not user or not password:
        print("[email] SMTP_USER/SMTP_PASSWORD absents — email non envoyé")
        return False

    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(user, password)
            server.sendmail(user, [to], msg.as_string())
        return True
    except smtplib.SMTPException as e:
        print(f"[email] échec d'envoi: {e}")
        return False


def _offer_html(o: dict) -> str:
    raison = (f"<p style='color:#555;font-style:italic'>&#129302; {o['llm_raison']}</p>"
              if o.get("llm_raison") else "")
    # Candidature par email possible (adresse non reproduite : à lire dans l'offre)
    mail_found, mail_ctx = signals.has_email_application(o)
    if mail_found and mail_ctx:
        mail_html = ("<p style='background:#fff4e5;border-left:4px solid #f0a020;"
                     "padding:8px 10px;margin:8px 0'><b>&#128231; Candidature par "
                     "email possible</b> &mdash; une adresse de contact figure dans "
                     "la description : pense &agrave; la lire.</p>")
    elif mail_found:
        mail_html = ("<p style='background:#f5f5f5;border-left:4px solid #bbb;"
                     "padding:8px 10px;margin:8px 0'>&#128231; Une adresse email "
                     "appara&icirc;t dans la description (&agrave; v&eacute;rifier).</p>")
    else:
        mail_html = ""

    posts_url = signals.linkedin_posts_url(o)
    posts_html = (f"<p><a href=\"{posts_url}\" style='color:#0a66c2'>&#128269; "
                  f"Chercher des posts LinkedIn (cooptation) chez "
                  f"{o.get('company','')}</a></p>" if posts_url else "")

    return (
        f"<h2 style='margin-bottom:2px'>{o['title']}</h2>"
        f"<p style='margin-top:2px'><b>{o['company']}</b> — {o.get('location','')} "
        f"— score <b>{o['score']}</b> — source {o['source']}"
        f"{' — publiée ' + str(o['date_posted']) if o.get('date_posted') else ''}</p>"
        f"{raison}"
        f"{mail_html}"
        f"<p><a href=\"{o['url']}\" style='font-size:16px'>&#9658; Voir l'offre et postuler</a></p>"
        f"{posts_html}"
    )


def send_alert(subject: str, text: str) -> None:
    """Email technique (panne/rétablissement de canal)."""
    _send(subject, f"<pre style='font-family:sans-serif'>{text}</pre>")


def notify(offers: list[dict], cfg: dict, dry_run: bool = False) -> None:
    """Un email par offre (les meilleures d'abord), puis un digest si dépassement."""
    if not offers:
        print("[email] aucune offre à notifier")
        return

    max_single = cfg.get("notification", {}).get("max_emails_par_run", 8)
    singles, rest = offers[:max_single], offers[max_single:]

    for o in singles:
        subject = f"\U0001F3AF [{o['score']}] {o['title'][:60]} — {o['company'][:40]}"
        if dry_run:
            print(f"[email:dry-run] {subject}\n    {o['url']}")
        else:
            ok = _send(subject, _offer_html(o))
            print(f"[email] {'envoyé' if ok else 'ÉCHEC'}: {subject}")

    if rest:
        subject = f"\U0001F4CB Stage Radar: {len(rest)} autres offres détectées"
        html = "".join(_offer_html(o) + "<hr>" for o in rest)
        if dry_run:
            print(f"[email:dry-run] {subject}")
        else:
            _send(subject, html)
