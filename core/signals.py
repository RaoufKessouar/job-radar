"""Signaux d'aide à la candidature extraits d'une offre.

1) Candidature par email : la description contient-elle une adresse email ?
   On ne remonte PAS l'adresse (elle se lit dans l'offre, avec ses consignes) —
   juste le fait qu'un envoi direct semble possible. Politique volontairement
   large : mieux vaut un signalement de trop qu'une piste ratée.

2) Lien de recherche de posts LinkedIn : URL prête à cliquer pour voir si
   quelqu'un de l'entreprise a publié un post au sujet du stage (cooptation).
"""

from __future__ import annotations

import re
import urllib.parse

# Adresse email standard, sans capturer la ponctuation finale
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)

# Faux positifs techniques à ignorer (jamais des adresses de candidature)
_IGNORE = re.compile(
    r"(@sentry\.|@2x|\.png$|\.jpg$|\.gif$|@example\.|@domain\.|@email\.com$)",
    re.I,
)

# Contexte typique d'une candidature (sert seulement à qualifier le message)
_APPLY_CONTEXT = re.compile(
    r"(candidat|postul|envoyez|envoyer|adressez|transmettez|cv\b|"
    r"lettre de motivation|apply|send your|resume|application)",
    re.I,
)


def has_email_application(offer: dict) -> tuple[bool, bool]:
    """(email_trouvé, contexte_candidature_autour).

    Le 2e booléen sert uniquement à nuancer la formulation du message.
    """
    desc = offer.get("description") or ""
    if not desc:
        return False, False

    found = [m for m in _EMAIL_RE.finditer(desc) if not _IGNORE.search(m.group(0))]
    if not found:
        return False, False

    # contexte : 200 caractères autour de la première adresse trouvée
    for m in found:
        start = max(0, m.start() - 200)
        window = desc[start:m.end() + 100]
        if _APPLY_CONTEXT.search(window):
            return True, True
    return True, False


def linkedin_posts_url(offer: dict) -> str:
    """Recherche de posts LinkedIn : mot 'stage'/'internship' + entreprise,
    triés par date de publication (les plus récents d'abord)."""
    company = (offer.get("company") or "").strip()
    if not company:
        return ""
    title = (offer.get("title") or "").lower()
    # langue du mot-clé alignée sur celle de l'intitulé de l'offre
    mot = "internship" if ("intern" in title and "stage" not in title) else "stage"
    keywords = f"{mot} {company}"
    return ("https://www.linkedin.com/search/results/content/?keywords="
            + urllib.parse.quote(keywords)
            + "&sortBy=%22date_posted%22")
