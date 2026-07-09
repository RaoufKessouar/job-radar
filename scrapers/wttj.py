"""Scraper Welcome to the Jungle via son API Algolia publique.

Format documenté et vérifié (2026) :
- endpoint : POST https://csekhvms53-dsn.algolia.net/1/indexes/*/queries
- index offres : wk_cms_jobs_production
- clé de recherche publique embarquée dans le front (la même pour tous les visiteurs)
- particularité Algolia : Content-Type doit être x-www-form-urlencoded
  alors que le corps est du JSON.
"""

from __future__ import annotations

import json
import time
import urllib.parse

import requests

SITE = "https://www.welcometothejungle.com"
ALGOLIA_URL = ("https://csekhvms53-dsn.algolia.net/1/indexes/*/queries"
               "?x-algolia-agent=Algolia%20for%20JavaScript%20(4.20.0)%3B%20Browser"
               "&search_origin=job_search_client")
DEFAULT_APP_ID = "CSEKHVMS53"
DEFAULT_API_KEY = "4bd8f6215d0cc52b26430765769e65a0"  # clé de recherche publique
DEFAULT_INDEX = "wk_cms_jobs_production"

# Géofiltre Île-de-France : centre Paris, rayon 60 km
IDF_LATLNG = "48.8566,2.3522"
IDF_RADIUS_M = 60000


def _headers(app_id: str, api_key: str) -> dict:
    return {
        "x-algolia-application-id": app_id,
        "x-algolia-api-key": api_key,
        "content-type": "application/x-www-form-urlencoded",
        "accept": "*/*",
        "origin": SITE,
        "referer": SITE + "/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126.0",
    }


def _query(session, app_id, api_key, index, keywords, hits_per_page, geo=True,
           max_age_jours=None):
    params = {
        "query": keywords,
        "hitsPerPage": hits_per_page,
        "page": 0,
        # internship (casse variable selon les versions de l'index → OR)
        "facetFilters": json.dumps([["contract_type:internship",
                                     "contract_type:INTERNSHIP"]]),
        "filters": "website.reference:wttj_fr",
    }
    if max_age_jours:
        cutoff = int(time.time()) - int(max_age_jours) * 86400
        params["numericFilters"] = json.dumps([f"published_at_timestamp>{cutoff}"])
    if geo:
        params["aroundLatLng"] = IDF_LATLNG
        params["aroundRadius"] = IDF_RADIUS_M
    body = {"requests": [{"indexName": index,
                          "params": urllib.parse.urlencode(params, safe=":,/")}]}
    r = session.post(ALGOLIA_URL, data=json.dumps(body),
                     headers=_headers(app_id, api_key), timeout=25)
    r.raise_for_status()
    result = r.json()["results"][0]
    if result.get("message"):  # erreur logique renvoyée en 200
        raise requests.RequestException(result["message"])
    return result.get("hits", [])


def _hit_to_offer(hit: dict) -> dict:
    org = hit.get("organization") or {}
    office = hit.get("office") or (hit.get("offices") or [{}])[0] or {}
    descs = org.get("descriptions") or {}
    desc = descs.get("fr") or descs.get("en") or ""
    return {
        "source": "wttj",
        "title": hit.get("name", ""),
        "company": org.get("name", ""),
        "location": office.get("city", ""),
        "url": f"{SITE}/fr/companies/{org.get('slug','')}/jobs/{hit.get('slug','')}",
        "date_posted": hit.get("published_at", ""),
        "description": str(desc)[:3000],
    }


def search(config: dict) -> list[dict]:
    wttj_cfg = config.get("wttj", {})
    app_id = wttj_cfg.get("algolia_app_id") or DEFAULT_APP_ID
    api_key = wttj_cfg.get("algolia_api_key") or DEFAULT_API_KEY
    index = wttj_cfg.get("algolia_index") or DEFAULT_INDEX
    hits_per_page = wttj_cfg.get("results_par_requete", 30)
    max_age = wttj_cfg.get("max_age_jours")

    session = requests.Session()
    offers, seen = [], set()
    geo_ok = True
    for rec in config.get("recherches", []):
        kw = rec["keywords"]
        hits = []
        try:
            hits = _query(session, app_id, api_key, index, kw, hits_per_page,
                          geo=geo_ok, max_age_jours=max_age)
        except requests.RequestException as e:
            if geo_ok:
                # l'index ne supporte peut-être pas le géofiltre → retry sans
                print(f"[wttj] géofiltre refusé ({e}) — retry sans filtre géo")
                geo_ok = False
                try:
                    hits = _query(session, app_id, api_key, index, kw,
                                  hits_per_page, geo=False, max_age_jours=max_age)
                except requests.RequestException as e2:
                    print(f"[wttj] requête '{kw}' échouée: {e2}")
                    continue
            else:
                print(f"[wttj] requête '{kw}' échouée: {e}")
                continue
        for hit in hits:
            offer = _hit_to_offer(hit)
            if offer["url"] not in seen:
                seen.add(offer["url"])
                offers.append(offer)
        time.sleep(1.0)  # politesse (≤4 req/s recommandé)

    if not geo_ok and offers:
        print("[wttj] NB: géofiltre inactif — offres hors IdF possibles ce run")
    print(f"[wttj] {len(offers)} offres récupérées")
    return offers
