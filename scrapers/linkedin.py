"""Scraper LinkedIn via python-jobspy (endpoint public guest, sans compte).

En cas de blocage temporaire (HTTP 429/999), on log et on continue :
les autres canaux (WTTJ) prennent le relais, et la dédup garantit
qu'aucune offre notifiable n'est perdue si elle réapparaît au run suivant.
"""

from __future__ import annotations

import time


def search(config: dict) -> list[dict]:
    try:
        from jobspy import scrape_jobs
    except ImportError:
        print("[linkedin] python-jobspy non installé — canal ignoré")
        return []

    location = config.get("localisation", {}).get("linkedin", "France")
    hours_old = config.get("linkedin", {}).get("hours_old", 2)
    wanted = config.get("linkedin", {}).get("results_par_requete", 20)

    offers, seen, failures = [], set(), 0
    for rec in config.get("recherches", []):
        kw = rec["keywords"]
        try:
            df = scrape_jobs(
                site_name=["linkedin"],
                search_term=kw,
                location=location,
                results_wanted=wanted,
                hours_old=hours_old,
                job_type="internship",
                country_indeed="france",
                linkedin_fetch_description=False,  # 1 requête/offre en plus si True → risque de rate-limit
                verbose=0,
            )
        except Exception as e:  # jobspy lève des exceptions variées selon le blocage
            failures += 1
            print(f"[linkedin] requête '{kw}' échouée ({type(e).__name__}): {e}")
            time.sleep(10)
            continue

        for _, row in df.iterrows():
            url = str(row.get("job_url", ""))
            if not url or url in seen:
                continue
            seen.add(url)
            offers.append({
                "source": "linkedin",
                "title": str(row.get("title", "") or ""),
                "company": str(row.get("company", "") or ""),
                "location": str(row.get("location", "") or ""),
                "url": url,
                "date_posted": str(row.get("date_posted", "") or ""),
                "description": str(row.get("description", "") or "")[:3000],
            })
        time.sleep(5)  # espacement entre les recherches pour rester sous le radar

    if failures == len(config.get("recherches", [])) and failures > 0:
        # Toutes les requêtes ont échoué → probablement bloqué. Signalé dans le rapport du run.
        print("[linkedin] ALERTE: toutes les requêtes ont échoué — canal probablement bloqué ce run")

    print(f"[linkedin] {len(offers)} offres récupérées ({failures} requête(s) échouée(s))")
    return offers
