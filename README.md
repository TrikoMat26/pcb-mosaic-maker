# PCB-Mosaic-Maker

Outil d'assemblage et d'inspection visuelle de cartes électroniques (PCB) à
partir de plusieurs photos partiellement recouvrantes.

---

## Pourquoi cet outil

Quand on photographie une carte trop grande ou trop fine pour tenir nette dans
un seul cadre (objectif macro, profondeur de champ limitée, éclairage de
microscope), il faut **plusieurs prises** qui se recouvrent partiellement. Le
besoin métier est de :

1. **Assembler** ces 2 à 10 photos en une seule mosaïque haute résolution.
2. **Annoter** la mosaïque pour signaler des défauts (composants manquants,
   soudures suspectes, traces abîmées, etc.) avec numérotation, type, sévérité.
3. **Mesurer** des dimensions sur la carte (calibration mm/pixel).
4. **Comparer** la carte produite avec une carte de référence (mode A/B,
   onion-skin, split-screen).
5. **Exporter** un livrable : image JPEG/PNG haute déf, rapport PDF, projet
   sauvegardable, et un JSON des annotations.

Cible d'utilisation : contrôle qualité électronique, retro-engineering,
documentation technique de prototypes, analyse de pannes.

---

## Deux implémentations dans ce repo

### A. Version Qt / Python (la version « officielle » historique)

```bash
pip install -r requirements.txt
python -m pcbmosaic.gui.main_window
```

Stack : `PySide6`, `opencv-python`, `numpy`, `scikit-image`, `Pillow`, `tqdm`.

Modules :

- `pcbmosaic/core/loader.py` — chargement et orientation EXIF
- `pcbmosaic/core/aligner.py` — détection de features + homographies
- `pcbmosaic/core/stitcher.py` — fusion (multiband / feather / overlay)
- `pcbmosaic/core/exporter.py` — export image / rapport
- `pcbmosaic/gui/main_window.py` — fenêtre principale Qt
- `pcbmosaic/gui/canvas_view.py` — vue canvas, zoom/pan, annotations
- `pcbmosaic/gui/tools_panel.py` — panneaux latéraux

### B. Version HTML autonome (`pcb-mosaic-maker.html`)

Page unique d'environ 2 400 lignes (HTML + CSS + JS dans un seul fichier),
qui charge **OpenCV.js** depuis le CDN `docs.opencv.org/4.x/opencv.js`.
Toute la logique tourne côté client, sans serveur.

**Lancement :**

```bash
# Le plus simple
xdg-open pcb-mosaic-maker.html        # Linux
open pcb-mosaic-maker.html            # macOS
start pcb-mosaic-maker.html           # Windows

# Si OpenCV.js refuse de charger en file:// (Firefox strict)
python -m http.server 8000
# puis http://localhost:8000/pcb-mosaic-maker.html
```

Premier lancement : ~10 Mo téléchargés depuis le CDN puis mis en cache.

---

## Pipeline d'assemblage (commun aux deux versions)

```
[Photos] -> [Décodage + EXIF] -> [Détection features] -> [Matching knn]
                                                              |
                                                              v
[Mosaïque finale] <- [Blend] <- [Warps perspectifs] <- [RANSAC + homographies]
                                                              |
                                                              v
                                              [Ajustements manuels par image
                                               via deltas pré-multipliés]
```

1. **Décodage + EXIF** : chaque photo est chargée et redressée selon
   l'orientation EXIF.
2. **Réduction (thumb)** : pour les calculs interactifs, chaque photo est
   réduite à ~1024 px max. Le bitmap original est conservé pour l'export
   final.
3. **Détection de points clés** : SIFT / ORB / AKAZE. La photo médiane sert
   de référence par défaut.
4. **Matching knn (k=2)** + ratio test de Lowe + RANSAC pour rejeter les
   correspondances aberrantes → une homographie 3×3 par photo.
5. **Warping perspectif** de chaque photo dans le repère de la mosaïque,
   plus calcul d'un masque doux (distance transform sur le canal alpha).
6. **Blending** : multiband Laplacien (le plus joli mais lourd), feather
   (moyenne pondérée), ou overlay (empilage simple).
7. **Ajustements manuels par image** : translation / rotation / échelle
   stockées sous forme de matrice 3×3 `delta[i]`, pré-multipliée à `H[i]`
   pour recalculer la mosaïque.

---

## Inventaire fonctionnel (version HTML)

| Fonction | État |
|---|---|
| Import multi-photos (drag & drop / file picker) | OK |
| Choix référence automatique (médiane) | OK |
| Alignement SIFT / ORB / AKAZE | Cassé en pratique (voir plus bas) |
| Sliders ratio test + seuil RANSAC | Calibration douteuse |
| 4 modes de blend (multiband, feather, average, overlay) | Multiband OOM au-delà de ~6 Mpx |
| Recalcul auto de la preview après nudge | OK (ajouté en cours de session) |
| Nudge clavier ←↑↓→ + Shift (×10) | Fonctionnel mais peu utilisable |
| Rotation Shift+molette / Échelle Alt+molette | Pas de feedback chiffré |
| Reset image / Reset tout | OK |
| Filtres globaux (luminosité, contraste, gamma, netteté, CLAHE, contours, N&B, invert) | OK mais **globaux uniquement** |
| Loupe (taille + zoom réglables) | OK |
| Annotations (cercle / flèche / rect / texte / mesure / calibration) | OK |
| Numérotation + type + sévérité défaut | OK |
| Calibration mm / pixel | OK |
| Mode A/B vs photo de référence (onion / split / diff) | OK |
| Alignement de la photo de réf sur la mosaïque | Hérite des problèmes SIFT |
| Export image (JPEG/PNG) | OK pour les tailles raisonnables |
| Export rapport PDF (généré côté JS) | OK |
| Export annotations JSON | OK |
| Sauvegarde / chargement projet (.pcbm.json) | OK |
| Raccourcis clavier (P/L/C/A/R/T/M/K/F/1) | OK |

---

## État actuel — Ce qui ne marche pas (synthèse honnête)

L'utilisateur a stoppé la session avec ce verdict : *« l'alignement ne donne
rien de cohérent, les ajustements sont fastidieux et inefficaces, l'interface
n'est pas ergonomique et moche, RIEN NE VA »*. Voici le détail technique.

### 1. L'alignement automatique est médiocre

**Cause racine** : la build d'OpenCV.js servie par
`docs.opencv.org/4.x/opencv.js` **ne contient pas SIFT** (le module
`xfeatures2d` est exclu). Les seuls détecteurs réellement disponibles dans
cette build sont **ORB** (et parfois AKAZE).

Conséquences :

- Le sélecteur UI propose SIFT / ORB / AKAZE mais SIFT est silencieusement
  remplacé par ORB via une factory de fallback (`makeFeatureDetector` au
  voisinage de la ligne 670 dans le HTML).
- Les seuils par défaut (ratio test 0.70, RANSAC 3.0) sont calibrés pour la
  distance L2 de SIFT. ORB utilise une distance de Hamming où ce ratio est
  **trop strict** → trop peu d'inliers → homographies bancales. Un
  ajustement automatique à 0.80 a été ajouté mais ne suffit pas sur les
  vraies photos PCB.
- Sur des images de PCB (peu de texture, beaucoup de répétitions
  composants/pistes), ORB seul produit des correspondances faibles. Sans
  filtrage géométrique fin (par ex. histogramme de translations dominantes),
  RANSAC laisse passer des homographies dégénérées.

**Pistes non explorées** :

- Compiler une build d'OpenCV.js custom **avec** `xfeatures2d` (SIFT, BRISK).
- Ou abandonner SIFT et utiliser un workflow **carrelage 2D simple** : les
  photos sont plus ou moins parallèles, l'utilisateur connaît l'ordre →
  estimer juste tx/ty par phase correlation (`cv.phaseCorrelate`), beaucoup
  plus stable que SIFT/ORB sur PCB.
- Ou imposer à l'utilisateur de cliquer 2-3 points correspondants entre
  chaque paire (alignement assisté) — beaucoup plus fiable.

### 2. Les ajustements manuels par image sont fastidieux

L'idée : pré-multiplier une matrice `delta[i]` à l'homographie et reconstruire
la mosaïque. Mais en pratique :

- **Latence** : chaque nudge déclenche un `buildPreview()` debounced à 350 ms,
  qui réexécute warp + blend de toutes les images. Sur un PCB de 6 photos,
  ça prend ~1-2 s sur un PC modeste → impression de saccade.
- **Pas de feedback live précis** : l'overlay semi-transparent montre la
  position approximative ; pas de zoom local, pas de cible d'alignement.
- **Pas de granularité fine** : Shift+flèche fait ×10, entre 1 et 10 px il
  n'y a rien. Pour un alignement sub-pixel (qui serait pertinent sur du PCB),
  le modèle est trop grossier.
- **Pas d'indicateurs chiffrés** : impossible de voir « tx = −12 px,
  rotation = 0,3° » pendant qu'on ajuste.

### 3. L'UI n'est pas ergonomique

Layout actuel : grid CSS à 3 colonnes (panneau gauche / canvas / panneau
droit). C'est fonctionnel mais :

- **Trop d'éléments visibles à la fois** : photos, alignement, blend,
  filtres, loupe, annotations, calibration, A/B — tout cohabite.
- **Pas de hiérarchie claire** entre étapes (1. importer, 2. aligner,
  3. ajuster, 4. annoter, 5. exporter). Les onglets du panneau droit sont
  censés aider mais ne sont pas pédagogiques.
- **Esthétique** : palette dark, accents bleus, look « outil tech ».
  L'utilisateur a explicitement trouvé ça « moche ». Une vraie app
  d'inspection PCB mériterait une charte graphique soignée et un
  onboarding.
- **Mobile / tablette : pas de support**. Un patch responsive a été commencé
  pendant la session puis annulé à la demande de l'utilisateur.

### 4. Mémoire WASM saturée sur grandes mosaïques

Le heap d'OpenCV.js fait ~256 MB. Le multiband Laplacien consomme environ
21·W·H bytes par image (pyramides Laplacienne CV_32FC3 + Gaussienne CV_32FC1
sur 4 niveaux). Conséquence : **OutOfMemory rapide** au-delà de quelques Mpx.

État actuel : `MAX_PREVIEW = 2500`, et au-delà de `N·W·H > 6 Mpx` on saute
multiband d'office et on attaque au feather. Les fuites Mat en cas
d'exception ont longtemps aggravé le problème ; corrigées en fin de session
via `try/finally` partout.

---

## Historique des tentatives faites pendant la session

Pour qui reprend, voici les commits dans l'ordre de la branche
`claude/python-to-html-conversion-kh3MO` :

| Commit | Sujet | Effet réel |
|---|---|---|
| `7b5ddfc` | HTML initial : portage Qt → page autonome | Base fonctionnelle mais avec bugs structurels |
| `09277b5` | Factory `makeFeatureDetector` SIFT → ORB → AKAZE | A débloqué le crash `cv.SIFT is not a constructor` mais l'alignement reste médiocre |
| `f83816e` | Overlay live aligné, rebuild auto debounced, ratio Hamming relâché | Ajustements deviennent visibles ; alignement ORB un peu meilleur |
| `ecbee0f` | `cvErr()` décode les pointeurs WASM, cascade de fallback fusion | On voit enfin les vrais messages d'erreur OpenCV |
| `ad93241` | Budget mémoire + `try/finally` dans tous les blends | Plus d'OOM en chaîne ; fallback feather robuste |

### Ce qui a fonctionné

- Décoder les exceptions WASM via `cv.exceptionFromPtr` → fini les
  `Erreur fusion : undefined`.
- `try/finally` autour de chaque allocation `Mat` → plus de fuite mémoire.
- Cascade `multiband → feather → overlay` avec `sleep(50)` entre tentatives
  pour laisser le moteur respirer.
- Mémorisation du frame de stitch (`this._stitchFrame`) pour que l'overlay
  live et la mosaïque de base partagent le même repère.

### Ce qui n'a PAS fonctionné

- Tenter de « rendre le projet utilisable » en colmatant des bugs sans
  remettre en cause l'architecture. Les vrais problèmes sont structurels :
  - SIFT absent de la build CDN ⇒ workflow d'alignement à repenser.
  - Le concept « delta × homographie + rebuild » est trop lourd pour une
    retouche fine interactive.
  - L'UI à 3 colonnes denses n'aide pas un utilisateur qui découvre le
    workflow.

---

## Pistes pour la suite (non explorées)

### Sur l'alignement

1. **Phase correlation par paires** (`cv.phaseCorrelate`) au lieu de SIFT/ORB
   pour les cas où les photos sont prises depuis le même angle (cas typique
   PCB sur table). Beaucoup plus stable, gratuit en CPU, et sub-pixel.
2. **Alignement assisté** : 2-3 clics par paire d'images sur des
   correspondances visibles (vias, traces caractéristiques) → homographie
   directe, robuste, pas besoin de features automatiques.
3. **Build OpenCV.js custom** avec `xfeatures2d` pour avoir SIFT/BRISK pour
   de vrai. Plus de Mo à charger mais ça résout 80 % des cas.
4. **Détection de grille** spécifique PCB : si l'utilisateur prend ses
   photos selon une grille connue (ex. 3×2), on peut ajouter cette
   contrainte forte au modèle.

### Sur les ajustements manuels

1. **Compositing canvas 2D natif** au lieu de rebuild OpenCV : chaque image
   dans son canvas propre, blend live via `globalCompositeOperation` et
   `globalAlpha`. On perd le multiband mais on gagne 60 fps.
2. **Indicateurs numériques** : afficher en temps réel `tx, ty, θ, scale`
   pendant l'édition, avec champs éditables.
3. **Drag & drop direct** de l'image sélectionnée sur le canvas, plus
   naturel que les flèches clavier.
4. **Pinch / 2 doigts** sur tablette pour rotation + scale combinés.
5. **Pas sub-pixel** : permettre des nudges de 0,5 px ou même 0,1 px en
   maintenant Ctrl par exemple.

### Sur l'UI

1. **Workflow par étapes** (wizard) : 1. import, 2. align, 3. ajustements,
   4. annotations, 5. export — un seul panneau visible à la fois, avec
   navigation linéaire.
2. **Refonte avec un framework** (Svelte / React) pour des composants
   maintenables au lieu d'un fichier monolithique de 2 400 lignes.
3. **Charte graphique** : couleurs douces, typographie soignée, onboarding,
   tooltips contextuels.
4. **Responsive** : layout vertical sur mobile, panneaux en drawers.

### Sur la mémoire / perf

1. **Web Workers** : warps et blends dans un worker pour ne pas bloquer
   l'UI.
2. **OffscreenCanvas** pour le compositing live.
3. **Tile-based rendering** pour les très grandes mosaïques (> 10 Mpx).

---

## Structure du repo

```
pcb-mosaic-maker/
├── README.md                      <- ce fichier
├── requirements.txt               <- deps Python (Qt)
├── pcb-mosaic-maker.html          <- version HTML autonome (~2 400 lignes)
├── pcbmosaic/                     <- version Python officielle
│   ├── core/
│   │   ├── aligner.py
│   │   ├── stitcher.py
│   │   ├── loader.py
│   │   └── exporter.py
│   ├── gui/
│   │   ├── main_window.py
│   │   ├── canvas_view.py
│   │   └── tools_panel.py
│   └── tests/
│       └── test_stitcher.py
└── examples/
    └── 20250427_*.jpg             <- 4 photos d'exemple d'un PCB
```

---

## Branches Git

- `main` : version Python Qt fonctionnelle (point d'entrée historique).
- `claude/python-to-html-conversion-kh3MO` : version HTML + corrections
  (commits listés plus haut).

Pour récupérer la branche HTML :

```bash
git fetch origin
git checkout claude/python-to-html-conversion-kh3MO
```

---

## TL;DR pour qui reprend

- L'app **fonctionne** sur les bases : import, fusion basique, annotations,
  export.
- L'alignement automatique est **bridé par le build CDN d'OpenCV.js** qui
  n'a pas SIFT — il faut soit changer de build, soit changer d'approche
  (phase correlation, alignement assisté à la souris).
- Les ajustements manuels par image **existent** mais sont **trop lents et
  pas assez fins** pour une vraie retouche. Refonte recommandée vers un
  compositing canvas 2D live.
- L'**UI** est dense et peu guidée : un workflow en étapes serait beaucoup
  plus accueillant pour un utilisateur métier.
- La **mémoire WASM** est un plafond dur à 256 MB ; toute opération qui
  alloue plus doit être streamée par tuiles, ou déléguée à un canvas 2D
  natif côté navigateur.
