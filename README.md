# 🎯 Stage Radar

Détection autonome d'offres de stage M2 Data Science / IA / ML / Computer Vision (Île-de-France) sur **Welcome to the Jungle** et **LinkedIn**, avec notification email dès qu'une offre pertinente apparaît. Scan toutes les 30 min via GitHub Actions.

L'objectif : être dans les 5 premiers candidats.

## Fonctionnement

```
GitHub Actions (cron */30, 7h-23h Paris)
  → scrapers/wttj.py      (API Algolia publique de WTTJ)
  → scrapers/linkedin.py  (endpoint guest via python-jobspy, SANS compte)
  → core/dedup.py         (state.json : jamais 2 notifications pour la même offre)
  → core/scoring.py       (score 0-100 selon config.yaml, seuil 30)
  → notify/emailer.py     (SMTP Gmail, 1 email par offre, lien direct)
```

## Installation (~15 min)

### 1. Test en local

```bash
pip install -r requirements.txt
python main.py --sample     # test hors-ligne (offres factices) : vérifie scoring + dédup + format email
rm state.json               # remettre l'état à zéro après le test
python main.py --dry-run    # vrai scraping, emails affichés mais pas envoyés
```

### 2. Mot de passe d'application Gmail

1. Active la validation en 2 étapes sur ton compte Google (obligatoire).
2. Va sur https://myaccount.google.com/apppasswords → crée un mot de passe nommé `stage-radar`.
3. Note les 16 caractères : c'est ton `SMTP_PASSWORD`.

### 3. Déploiement GitHub Actions

1. Crée un repo GitHub **privé** et pousse ce dossier :
   ```bash
   git init && git add -A && git commit -m "init stage-radar"
   git branch -M main
   git remote add origin https://github.com/TON_USER/stage-radar.git
   git push -u origin main
   ```
2. Dans le repo : *Settings → Secrets and variables → Actions → New repository secret* :
   - `SMTP_USER` = ton adresse Gmail
   - `SMTP_PASSWORD` = le mot de passe d'application (16 caractères)
   - `NOTIFY_TO` = adresse qui reçoit les alertes (peut être la même)
3. Onglet *Actions* → workflow **Stage Radar scan** → *Run workflow* pour un premier test manuel.
4. C'est tout : le cron prend le relais toutes les 30 min.

### 4. Notifications instantanées sur téléphone

Dans Gmail mobile, crée un libellé/filtre sur l'objet `🎯` avec notification activée → alerte push quasi temps réel.

## Régler la pertinence

Tout se passe dans `config.yaml` : requêtes, mots-clés bonus et leurs poids, exclusions, seuil. Après quelques jours, ajuste selon les faux positifs/négatifs reçus. Aucun code à toucher.

## Bon à savoir

- **Aucun compte LinkedIn n'est utilisé** : uniquement les pages publiques. Ton compte ne risque rien.
- Si LinkedIn bloque temporairement les IPs de GitHub (log `canal probablement bloqué`), WTTJ continue. Si ça devient fréquent : passer le job sur un petit VPS ou ajouter un proxy dans `linkedin.py`.
- Le scraper WTTJ découvre automatiquement les clés Algolia du site à chaque run — il survit donc aux rotations de clés.
- `state.json` est commité à chaque run : c'est la mémoire anti-doublons ET ton historique d'offres.
- Coût : 0 €. Le cron (~37 runs/jour × ~2 min) reste sous les 2000 min/mois gratuites des repos privés.
