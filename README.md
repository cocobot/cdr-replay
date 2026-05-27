# CDR Replay

Archive navigable des matchs de la **Coupe de France de Robotique**, générée
automatiquement à partir des flux de diffusion YouTube.

Le générateur lit l'overlay de diffusion (numéro de table, noms d'équipes,
décompte) image par image, en déduit la liste des matchs de chaque série, et
produit un **site statique** (GitHub Pages) où l'on peut :

- choisir **junior / senior**, l'**année**, puis la **série** → un viewer qui
  embarque la vidéo et liste les matchs (saut au bon timestamp) ;
- chercher une **équipe** et voir tous ses matchs à travers les années.

> La localisation des robots sur la table viendra en v2.

## Comment ça marche

- **Fonte fixe** : l'overlay utilise *Ethnocentric*, mal lue par un OCR
  générique. On reconnaît chaque glyphe par template matching contre des
  gabarits rendus une fois depuis la fonte (`cdr_replay/data/templates.npz`).
- **Détection de bandeau** : l'OCR ne tourne que lorsque le bandeau de match est
  affiché (barres grises caractéristiques) — pas pendant les replays / plateau /
  transitions → pas de faux matchs.
- **Segmentation** : par numéro de table (lissé), vote majoritaire des noms,
  fusion des fragments d'un même match. Chaque match démarre **3 s avant le
  décompte**.
- **Roster optionnel** : `config/teams.txt` recale les noms sur la liste
  officielle (sinon, OCR brut).

Tout ce qui dépend de la mise en page de l'overlay est dans
`OverlayConfig` (`cdr_replay/overlay.py`) — une autre compétition (junior…) se
gère en ajustant les zones, sans toucher à l'algorithme.

## Utilisation

```bash
pip install -r requirements.txt      # + le binaire `tesseract`
# 1) (re)générer les gabarits depuis une planche de glyphes de la fonte (une fois)
python -m cdr_replay templates chemin/vers/ethnocentric.png
# 2) parser les vidéos de config/videos.yaml -> site/data/
python -m cdr_replay build --ocr-fps 1
```

Éditer `config/videos.yaml` pour ajouter des vidéos :

```yaml
roster: config/teams.txt
videos:
  - {category: senior, year: 2026, series: "3", youtube: "https://www.youtube.com/watch?v=…"}
  - {category: junior, year: 2026, series: "2", youtube: "https://www.youtube.com/watch?v=…"}
```

`series` : `"1"`…`"5"` puis `"finales"`. Les vidéos sont téléchargées en 720p
dans `.cache/` (non versionné). Les données générées (`site/data/`) sont
commitées et déployées par GitHub Actions.

## Déploiement

Le workflow `.github/workflows/deploy.yml` publie le dossier `site/` sur GitHub
Pages à chaque push sur `main`.
