"""Scraper Welcome to the Jungle via son API de recherche Algolia.

WTTJ expose sa recherche via Algolia. L'application ID et la clé de recherche
(publique, lecture seule) sont embarquées dans le front du site. Comme WTTJ
peut les faire tourner, on tente d'abord les valeurs connues, puis on
re-découvre automatiquement les credentials dans le HTML du site si besoin.
"""

from __future__ import annotations

import re
import time
import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

# Valeurs connues (peuvent changer — la découverte automatique prend le relais)
DEFAULT_APP_ID = "CSEKHVMS53"
DEFAULT_INDEX = "wttj_jobs_production"

_KEY_PATTERNS = [
    re.compile(r'ALGOLIA_APPLICATION_ID["\']?\s*[:=]\s*["\']([A-Z0-9]{8,12})["\']'),
    re.compile(r'applicationId["\']?\s*[:=]\s*["\']([A-Z0-9]{8,12})["\']'),
]
_API_KEY_PATTERNS = [
    re.compile(r'ALGOLIA_API_KEY(?:_CLIENT)?["\']?\s*[:=]\s*["\']([a-f0-9]{32})["\']'),
    re.compile(r'searchApiKey["\']?\s*[:=]\s*["\']([a-f0-9]{32})["\']'),
    re.compile(r'apiKey["\']?\s*[:=]\s*["\']([a-f0-9]{32})["\']'),
]


def _discover_credentials(session: requests.Session) -> tuple[str | None, str | None]:
    """Extrait appId + clé de recherche Algolia depuis le front WTTJ."""
    try:
        html = session.get(
            "https://www.welcometothejungle.com/fr/jobs",
            headers={"User-Agent": UA}, timeout=20,
        ).text
    except requests.RequestException:
        return None, None

    app_id = next((m.group(1) for p in _KEY_PATTERNS if (m := p.search(html))), None)
    api_key = next((m.group(1) for p in _API_KEY_PATTERNS if (m := p.search(html))), None)

    # Les credentials sont parfois dans un bundle JS référencé par la page
    if not api_key:
        for js_url in re.findall(r'src="(https://[^"]+\.js)"', html)[:8]:
            try:
                js = session.get(js_url, headers={"User-Agent": UA}, timeout=15).text
            except requests.RequestException:
                continue
            app_id = app_id or next((m.group(1) for p in _KEY_PATTERNS if (m := p.search(js))), None)
            api_key = next((m.group(1) for p in _API_KEY_PATTERNS if (m := p.search(js))), None)
            if api_key:
                break
    return app_id, api_key


def _resolve_index(session, app_id, api_key, configured: str) -> str | None:
    """Trouve l'index Algolia des offres : teste le nom configuré, sinon
    interroge la liste des index et prend le premier contenant 'jobs'."""
    headers = {"User-Agent": UA, "x-algolia-application-id": app_id,
               "x-algolia-api-key": api_key}
    base = f"https://{app_id.lower()}-dsn.algolia.net/1/indexes"

    def works(name: str) -> bool:
        try:
            r = session.post(f"{base}/{name}/query",
                             json={"query": "stage", "hitsPerPage": 1},
                             headers=headers, timeout=15)
            return r.status_code == 200 and r.json().get("nbHits", 0) > 0
        except requests.RequestException:
            return False

    candidates = [configured, DEFAULT_INDEX, "wttj_jobs_production_fr",
                  "wttj_jobs_production_published_at_desc"]
    # Liste officielle des index si la clé le permet
    try:
        r = session.get(base, headers=headers, timeout=15)
        if r.status_code == 200:
            names = [it["name"] for it in r.json().get("items", [])]
            candidates += [n for n in names
                           if "job" in n.lower() and "organization" not in n.lower()]
    except requests.RequestException:
        pass

    seen = set()
    for name in candidates:
        if not name or name in seen:
            continue
        seen.add(name)
        if works(name):
            if name != configured:
                print(f"[wttj] index résolu automatiquement: {name}")
            return name
    return None


def _query_algolia(session, app_id, api_key, keywords, state, hits_per_page,
                   index=DEFAULT_INDEX):
    url = f"https://{app_id.lower()}-dsn.algolia.net/1/indexes/{index}/query"
    facet_filters = [["contract_type:internship"]]
    if state:
        facet_filters.append([f"offices.state:{state}"])
    body = {
        "query": keywords,
        "hitsPerPage": hits_per_page,
        "facetFilters": facet_filters,
        "attributesToRetrieve": [
            "name", "slug", "organization", "offices",
            "published_at", "profile", "contract_type",
        ],
    }
    r = session.post(
        url, json=body, timeout=20,
        headers={
            "User-Agent": UA,
            "x-algolia-application-id": app_id,
            "x-algolia-api-key": api_key,
        },
    )
    r.raise_for_status()
    return r.json().get("hits", [])


def _hit_to_offer(hit: dict) -> dict:
    org = hit.get("organization") or {}
    offices = hit.get("offices") or []
    city = offices[0].get("city", "") if offices else ""
    slug, org_slug = hit.get("slug", ""), org.get("slug", "")
    return {
        "source": "wttj",
        "title": hit.get("name", ""),
        "company": org.get("name", ""),
        "location": city,
        "url": f"https://www.welcometothejungle.com/fr/companies/{org_slug}/jobs/{slug}",
        "date_posted": hit.get("published_at", ""),
        "description": (hit.get("profile") or "")[:3000],
    }


def search(config: dict) -> list[dict]:
    """Lance toutes les requêtes configurées sur WTTJ. Retourne une liste d'offres normalisées."""
    session = requests.Session()
    state = config.get("localisation", {}).get("wttj_state")
    hits_per_page = config.get("wttj", {}).get("results_par_requete", 20)

    # 1) Clés fixées dans config.yaml (prioritaires), 2) découverte automatique
    wttj_cfg = config.get("wttj", {})
    app_id = wttj_cfg.get("algolia_app_id") or DEFAULT_APP_ID
    index = wttj_cfg.get("algolia_index") or DEFAULT_INDEX
    api_key = wttj_cfg.get("algolia_api_key") or None
    if not api_key:
        discovered_app, discovered_key = _discover_credentials(session)
        if discovered_app and discovered_key:
            app_id, api_key = discovered_app, discovered_key
    if not api_key:
        print("[wttj] ERREUR: pas de clé Algolia (ni config, ni découverte auto) — canal WTTJ ignoré ce run")
        print("[wttj] Fix: renseigner wttj.algolia_app_id / algolia_api_key dans config.yaml (voir README)")
        return []

    resolved = _resolve_index(session, app_id, api_key, index)
    if not resolved:
        print("[wttj] ERREUR: aucun index d'offres accessible avec cette clé — canal ignoré ce run")
        return []
    index = resolved

    offers, seen = [], set()
    for rec in config.get("recherches", []):
        kw = rec["keywords"]
        try:
            hits = _query_algolia(session, app_id, api_key, kw, state, hits_per_page, index)
        except requests.RequestException as e:
            print(f"[wttj] requête '{kw}' échouée: {e}")
            continue
        for hit in hits:
            offer = _hit_to_offer(hit)
            if offer["url"] not in seen:
                seen.add(offer["url"])
                offers.append(offer)
        time.sleep(1.5)  # politesse entre les requêtes
    print(f"[wttj] {len(offers)} offres récupérées")
    return offers
