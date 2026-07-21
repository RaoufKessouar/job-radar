"""Scrapers des sites carrières officiels (détection à la source).

Entreprises couvertes :
- Renault, Valeo  → Workday (API JSON publique du portail carrière)
- Orange          → Phenom People (API /widgets)

Principes :
- On ne récupère que la LISTE au scan (2-3 requêtes/entreprise). Les
  descriptions détaillées sont récupérées à la demande (enrich_descriptions),
  uniquement pour les nouvelles offres candidates — comme la 2e passe LinkedIn.
- Filtres côté site resserrés au stage pur. Les identifiants de facettes
  Workday sont résolus dynamiquement par leur libellé (stagiaire/trainee/
  intern), avec repli sur les valeurs connues si la résolution échoue.
- Aucun scoring ici : le jugement appartient au pipeline (gate + Gemini).

search(config) -> (offers, fetch_ok)  où fetch_ok = {entreprise: bool}
(fetch_ok alimente la surveillance santé : un site carrière peut légitimement
avoir 0 offre — c'est l'échec de REQUÊTE qui est anormal, pas le vide.)
"""

from __future__ import annotations

import html as html_lib
import json
import re
import time

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
TIMEOUT = 25

# ---------------------------------------------------------------- utilitaires

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_html(text: str) -> str:
    text = _TAG_RE.sub(" ", str(text or ""))
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


def _get(url: str, as_json: bool = True):
    r = requests.get(url, headers={"User-Agent": UA,
                                   "Accept-Language": "fr-FR,fr;q=0.9"},
                     timeout=TIMEOUT)
    r.raise_for_status()
    return r.json() if as_json else r.text


def _post_json(url: str, payload: dict) -> dict:
    r = requests.post(url, json=payload,
                      headers={"User-Agent": UA,
                               "Accept-Language": "fr-FR,fr;q=0.9"},
                      timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


# ------------------------------------------------------------------- Workday

WORKDAY = {
    "renault": {
        "company": "Renault Group",
        "jobs_url": "https://alliancewd.wd3.myworkdayjobs.com/wday/cxs/alliancewd/renault-group-careers/jobs",
        "public_base_url": "https://alliancewd.wd3.myworkdayjobs.com/fr-FR/renault-group-careers",
        "detail_base_url": "https://alliancewd.wd3.myworkdayjobs.com/wday/cxs/alliancewd/renault-group-careers",
        # repli si la résolution dynamique échoue (libellés Trainee/Intern)
        "fallback_worker_subtypes": ["62e55b3e447c01fa9aabbaa4ca0f9591",
                                     "62e55b3e447c01d10acebaa4ca0f9691"],
        "fallback_country": "54c5b6971ffb4bf0b116fe7651ec789a",  # France
    },
    "valeo": {
        "company": "Valeo",
        "jobs_url": "https://valeo.wd3.myworkdayjobs.com/wday/cxs/valeo/valeo_jobs/jobs",
        "public_base_url": "https://valeo.wd3.myworkdayjobs.com/fr-FR/valeo_jobs",
        "detail_base_url": "https://valeo.wd3.myworkdayjobs.com/wday/cxs/valeo/valeo_jobs",
        # repli : les 3 ids connus couvrent Apprentice/Trainee/VIE (large) —
        # le gate + Gemini écartent alors l'alternance/VIE
        "fallback_worker_subtypes": ["1bc7ee912dc9100bd4a8277106db0000",
                                     "1bc7ee912dc9100bd4a8277106db0002",
                                     "1bc7ee912dc9100bd4a826d6e65d0000"],
        "fallback_country": "54c5b6971ffb4bf0b116fe7651ec789a",
    },
}

_STAGE_LABELS = re.compile(r"stagiaire|trainee|intern(?!al)", re.I)
_NON_STAGE_LABELS = re.compile(r"apprenti|alternan|apprentice|vie\b|working student", re.I)


def _workday_resolve_facets(jobs_url: str) -> tuple[list[str], list[str]]:
    """Résout dynamiquement les ids de facettes 'stage' et 'France'.
    Retourne ([worker_subtype_ids], [country_ids]) — listes vides si échec."""
    resp = _post_json(jobs_url, {"appliedFacets": {}, "limit": 1,
                                 "offset": 0, "searchText": ""})
    subtypes, countries = [], []
    for facet in resp.get("facets") or []:
        param = str(facet.get("facetParameter") or "")
        for value in facet.get("values") or []:
            label = str(value.get("descriptor") or "")
            vid = str(value.get("id") or "")
            if not vid:
                continue
            if param == "workerSubType":
                if _STAGE_LABELS.search(label) and not _NON_STAGE_LABELS.search(label):
                    subtypes.append(vid)
            elif param == "locationCountry" and label.strip().lower() == "france":
                countries.append(vid)
    return subtypes, countries


def _workday_list(name: str, conf: dict, limit: int = 20,
                  max_pages: int = 10) -> list[dict]:
    try:
        subtypes, countries = _workday_resolve_facets(conf["jobs_url"])
    except (requests.RequestException, ValueError):
        subtypes, countries = [], []
    if not subtypes:
        subtypes = conf["fallback_worker_subtypes"]
        print(f"[carriere-{name}] facettes stage non résolues — repli sur ids connus (filtre large)")
    if not countries:
        countries = [conf["fallback_country"]]

    facets = {"workerSubType": subtypes, "locationCountry": countries}
    offers, offset, total = [], 0, None
    for _ in range(max_pages):
        page = _post_json(conf["jobs_url"], {"appliedFacets": facets,
                                             "limit": limit, "offset": offset,
                                             "searchText": ""})
        if total is None:
            total = int(page.get("total") or 0)
        for item in page.get("jobPostings") or []:
            path = str(item.get("externalPath") or "").strip()
            title = str(item.get("title") or "").strip()
            if not path or not title:
                continue
            offers.append({
                "source": f"carriere-{name}",
                "title": title,
                "company": conf["company"],
                "location": str(item.get("locationsText") or ""),
                "url": conf["public_base_url"] + path,
                "date_posted": str(item.get("postedOn") or ""),
                "description": "",
                "_detail_url": conf["detail_base_url"] + path,
            })
        offset += limit
        if offset >= (total or 0):
            break
        time.sleep(1.0)
    return offers


def _workday_detail(offer: dict) -> None:
    detail = _get(offer["_detail_url"])
    info = detail.get("jobPostingInfo") or {}
    offer["description"] = _clean_html(info.get("jobDescription") or "")[:3000]
    if info.get("startDate"):
        offer["date_posted"] = str(info["startDate"])


# -------------------------------------------------------------------- Orange

ORANGE_WIDGET_URL = "https://orange.jobs/widgets"
ORANGE_PUBLIC_BASE = "https://orange.jobs/fr/fr/job"


def _orange_payload(size: int, offset: int) -> dict:
    return {
        "lang": "fr_fr", "deviceType": "desktop", "country": "fr",
        "pageName": "search-results", "size": size, "from": offset,
        "jobs": True, "counts": True,
        "all_fields": ["category", "country", "city", "contractType",
                       "hiringType", "companyName", "workModel"],
        "clearAll": False, "jdsource": "facets", "isSliderEnable": False,
        "pageId": "page25", "siteType": "external", "keywords": "",
        "global": False, "locationData": {}, "refNum": "OYVOCZGB",
        "ddoKey": "refineSearch",
        "selected_fields": {"country": ["FRANCE"],
                            "contractType": ["Stage"]},   # stage pur
        "sort": {"order": "desc", "field": "postedDate"},
    }


def _orange_list(size: int = 100, max_pages: int = 3) -> list[dict]:
    offers, offset, total = [], 0, None
    for _ in range(max_pages):
        resp = _post_json(ORANGE_WIDGET_URL, _orange_payload(size, offset))
        result = resp.get("refineSearch") or {}
        if total is None:
            total = int(result.get("totalHits") or 0)
        for item in (result.get("data") or {}).get("jobs") or []:
            req_id = str(item.get("reqId") or item.get("jobId") or "")
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            ml = item.get("ml_job_parser")
            teaser = ((ml or {}).get("descriptionTeaser_ats")
                      if isinstance(ml, dict) else "") or item.get("descriptionTeaser") or ""
            import urllib.parse as _up
            slug = _up.quote(title.replace(" ", "-"), safe="")
            offers.append({
                "source": "carriere-orange",
                "title": title,
                "company": "Orange",
                "location": str(item.get("cityStateCountry")
                                or item.get("city") or "France"),
                "url": f"{ORANGE_PUBLIC_BASE}/{req_id}/{slug}" if req_id else ORANGE_PUBLIC_BASE,
                "date_posted": str(item.get("postingStartDate")
                                   or item.get("postedDate") or "")[:10],
                "description": _clean_html(teaser)[:3000],
            })
        offset += size
        if offset >= (total or 0):
            break
        time.sleep(1.0)
    return offers


def _orange_detail(offer: dict) -> None:
    page = _get(offer["url"], as_json=False)
    marker = "phApp.ddo = "
    start = page.find(marker)
    if start < 0:
        return
    brace = page.find("{", start + len(marker))
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(page[brace:], start=brace):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    ddo = json.loads(page[brace:i + 1])
                    job = (((ddo.get("jobDetail") or {}).get("data") or {})
                           .get("job") or {})
                    desc = _clean_html(job.get("description") or "")
                    if desc:
                        offer["description"] = desc[:3000]
                    return


# ----------------------------------------------------------------- Capgemini

CAPGEMINI_API = "https://cg-jobstream-api.azurewebsites.net/api/job-search"


def _capgemini_list(size: int = 50, max_pages: int = 4) -> list[dict]:
    offers, page, total = [], 1, None
    while page <= max_pages:
        params = {"page": page, "size": size, "country_code": "fr-fr",
                  "contract_type": "Stage",
                  "experience_level": "Etudiants/ Jeunes diplômés"}
        r = requests.get(CAPGEMINI_API, params=params,
                         headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        resp = r.json()
        if total is None:
            total = int(resp.get("count") or 0)
        for item in resp.get("data") or []:
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            url = str(item.get("wp_url") or item.get("job_url")
                      or item.get("url") or "").split("?", 1)[0]
            offers.append({
                "source": "carriere-capgemini",
                "title": title,
                "company": "Capgemini",
                "location": str(item.get("location") or item.get("city") or ""),
                "url": url,
                "date_posted": str(item.get("created_at")
                                   or item.get("published_at") or "")[:10],
                # description fournie directement dans la liste
                "description": _clean_html(item.get("description") or "")[:3000],
            })
        if page * size >= (total or 0):
            break
        page += 1
        time.sleep(1.0)
    return offers


# ------------------------------------------------------------------ Dassault

DASSAULT_SEARCH = "https://www.3ds.com/apisearch/card_search_api"
DASSAULT_DETAIL = "https://www.3ds.com/apisearch/GetCareerCardDetailV2"
DASSAULT_PUBLIC = "https://www.3ds.com/careers/jobs"


def _dassault_metas(hit: dict) -> dict:
    values = {}
    for meta in hit.get("metas") or []:
        name, value = meta.get("name"), meta.get("value")
        if name and name != "meta_cat" and name not in values:
            values[name] = value
    return values


def _dassault_list(size: int = 60, max_pages: int = 3) -> list[dict]:
    # Internship uniquement (pas d'Apprenticeship : cible stage pur)
    query = ('#all card_content_lang:en  (card_content_type="career")  '
             'card_content_categories:("Type/Internship" AND "Country/France")')
    offers, index, total = [], 0, None
    while index < max_pages:
        r = requests.get(DASSAULT_SEARCH,
                         params={"q": query, "b": index * size, "hf": size,
                                 "output_format": "json",
                                 "s": "desc(card_content_start_datetime)"},
                         headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        resp = r.json()
        if total is None:
            total = int(resp.get("nhits") or resp.get("nmatches") or 0)
        for hit in resp.get("hits") or []:
            metas = _dassault_metas(hit)
            title = str(metas.get("content_title") or "").strip()
            card_id = str(metas.get("card_id") or hit.get("did") or "")
            if not title:
                continue
            date_raw = str(metas.get("content_start_datetime") or "")
            m = re.search(r"\d{4}-\d{2}-\d{2}", date_raw)
            offers.append({
                "source": "carriere-dassault",
                "title": title,
                "company": "Dassault Systemes",
                "location": str(metas.get("content_info_2_value") or "France"),
                "url": str(metas.get("content_cta_1_url")
                           or f"{DASSAULT_PUBLIC}/{card_id}"),
                "date_posted": m.group(0) if m else date_raw[:10],
                "description": _clean_html(metas.get("content_summary") or "")[:3000],
                "_dassault_id": card_id,
            })
        index += 1
        if index * size >= (total or 0):
            break
        time.sleep(1.0)
    return offers


def _dassault_detail(offer: dict) -> None:
    card_id = offer.get("_dassault_id", "")
    if not card_id:
        return
    detail = _get(f"{DASSAULT_DETAIL}/en/{card_id}")
    metas = _dassault_metas((detail.get("hits") or [{}])[0])
    parts = [metas.get("external_description"), metas.get("external_qualification")]
    desc = _clean_html(" ".join(str(p or "") for p in parts))
    if desc:
        offer["description"] = desc[:3000]
    slug = str(metas.get("slug") or "")
    if slug:
        offer["url"] = f"{DASSAULT_PUBLIC}/{slug}"


# ------------------------------------------------------------------ pipeline

def search(config: dict) -> tuple[list[dict], dict]:
    """Collecte les listes d'offres des sites carrières activés.
    Retourne (offres, fetch_ok par entreprise)."""
    car_cfg = config.get("carrieres", {})
    entreprises = car_cfg.get("entreprises", {})
    offers, fetch_ok = [], {}

    for name in ("renault", "valeo"):
        if not entreprises.get(name, {}).get("actif"):
            continue
        try:
            found = _workday_list(name, WORKDAY[name])
            offers.extend(found)
            fetch_ok[name] = True
            print(f"[carriere-{name}] {len(found)} offres listées")
        except (requests.RequestException, ValueError, KeyError) as e:
            fetch_ok[name] = False
            print(f"[carriere-{name}] ÉCHEC de collecte: {e}")
        time.sleep(1.0)

    autres = {"orange": _orange_list, "capgemini": _capgemini_list,
              "dassault": _dassault_list}
    for name, collect in autres.items():
        if not entreprises.get(name, {}).get("actif"):
            continue
        try:
            found = collect()
            offers.extend(found)
            fetch_ok[name] = True
            print(f"[carriere-{name}] {len(found)} offres listées")
        except (requests.RequestException, ValueError, KeyError) as e:
            fetch_ok[name] = False
            print(f"[carriere-{name}] ÉCHEC de collecte: {e}")
        time.sleep(1.0)

    return offers, fetch_ok


def enrich_descriptions(offers: list[dict], config: dict) -> None:
    """Récupère le détail des seules nouvelles offres candidates (post-dédup)."""
    cap = config.get("carrieres", {}).get("max_descriptions_par_run", 15)
    done = 0
    for o in offers:
        src = o.get("source", "")
        if not src.startswith("carriere-"):
            continue
        if done >= cap:
            print(f"[carrieres] plafond descriptions atteint ({cap})")
            break
        try:
            if "_detail_url" in o:
                _workday_detail(o)
            elif "_dassault_id" in o and len(o.get("description", "")) < 300:
                _dassault_detail(o)
            elif src == "carriere-orange" and len(o.get("description", "")) < 300:
                _orange_detail(o)
            else:
                continue
            done += 1
            time.sleep(1.0)
        except (requests.RequestException, ValueError, json.JSONDecodeError):
            continue
    if done:
        print(f"[carrieres] {done} description(s) détaillée(s) récupérée(s)")
