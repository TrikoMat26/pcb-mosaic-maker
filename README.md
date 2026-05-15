# PCB-Mosaic-Maker

Outil desktop Windows pour **assembler des photos partiellement recouvrantes
d'une carte électronique** en une mosaïque haute résolution, puis pour
**comparer un autre PCB à cette image de référence** afin de faire ressortir
les défauts (composants manquants, soudures suspectes, pistes endommagées).

Stack : Python 3.10+, PySide6, OpenCV, scikit-image, Pillow. Distribué sous
forme de `.exe` portable via PyInstaller.

> **Pour qui reprend le développement (notamment via Claude Code) :**
> ce README est le document de référence à jour. Le `CHANGELOG.md` détaille
> l'historique fonctionnel par version. Lis les deux avant de modifier
> quoi que ce soit.

---

## Pourquoi cet outil

Photographier un PCB en macro / microscope = champ trop étroit pour tenir
toute la carte dans une prise nette. La solution : prendre 2 à 20 photos
qui se recouvrent partiellement, les **assembler** en une mosaïque, puis
utiliser cette mosaïque comme **référence d'inspection**. Quand un nouveau
PCB sort de la chaîne, on le photographie de la même manière, on l'aligne
sur la référence, et l'outil met en évidence les différences. Cible
métier : contrôle qualité électronique, rétro-engineering, analyse de
pannes.

---

## Installation rapide

### Lancement développement

```bash
git clone <repo>
cd pcb-mosaic-maker
pip install -r requirements.txt
python run.py
```

`requirements.txt` : `PySide6 >= 6.7`, `numpy`, `opencv-python`, `Pillow`,
`scikit-image`, `tqdm`.

### Build d'un `.exe` portable Windows

```powershell
pip install -r requirements-dev.txt
.\build.ps1
# → dist\PCB-Mosaic-Maker.exe (≈150 MB)
```

Le `.spec` PyInstaller (`pcbmosaic.spec`) exclut les modules Qt inutiles
(WebEngine, Multimedia, Charts, 3D, Bluetooth…) pour limiter la taille.

---

## Workflow utilisateur

L'application est organisée en quatre étapes, exposées dans la barre de
menus.

### 1. Fichier → Ouvrir / Ajouter des photos

- **Ouvrir des photos** (`Ctrl+O`) : sélection initiale (2 à 20 photos).
  Réinitialise le lot et les clics éventuels d'une session précédente.
- **Ajouter des photos** (`Ctrl+Shift+O`) : complète le lot courant —
  utile pour piocher dans plusieurs dossiers. **L'alignement existant des
  photos déjà chargées est préservé** (auto-align, clics, ajustements
  souris). Seules les nouvelles photos sont alignées, par paire avec la
  dernière photo existante, puis chaînées vers le repère global.
  En cas d'échec d'alignement d'une nouvelle photo, un rollback complet
  ramène à l'état d'avant l'ajout.

L'orientation EXIF est appliquée via `PIL.ImageOps.exif_transpose`.
Si une photo reste mal orientée (EXIF absent ou faux), voir le menu
**Photos** ci-dessous.

### 2. Alignement

Trois modes automatiques + un mode assisté par clics.

| Mode    | Algo                                     | Cas d'usage                                                              |
|---------|------------------------------------------|--------------------------------------------------------------------------|
| `phase` | `cv2.phaseCorrelate` par paires          | Photos prises depuis la même incidence (recommandé pour PCB sur table).  |
| `sift`  | SIFT + RANSAC, homographie complète      | Surfaces texturées, perspective variable. Fragile sur PCB répétitifs.    |
| `orb`   | ORB + RANSAC                             | Fallback si SIFT indisponible. Moins discriminant que SIFT.              |

Le mode `phase` est par défaut. Tous les modes assument que les photos
sont chargées **dans l'ordre de capture** (la photo *n* est voisine de
la photo *n+1*) et placent la photo médiane comme référence (pour le
chaînage et le repère, pas pour l'ordre d'empilage).

**Mode assisté par clics** : *Référence → Aligner par clics…* (`Ctrl+L`).
Ouvre une boîte modale avec deux photos consécutives côte à côte. On
clique alternativement GAUCHE puis DROITE sur le même point physique
(via, coin de composant, test point…). **Minimum 3 paires par couple
d'images** (translation + rotation + échelle déterminées de façon robuste
même avec un clic imprécis). Estimation par similarité via
`cv2.estimateAffinePartial2D` en RANSAC. Navigation entre paires via les
boutons ou `PgUp` / `PgDown`, annulation par `Ctrl+Z`.

Robustesse :

- Les **clics sont persistants** : rouvrir la boîte réaffiche les
  correspondances déjà saisies, prêtes à être ajustées ou complétées.
- Si une nouvelle photo a été ajoutée après un premier click-align, les
  paires déjà cliquées sont préservées et seule la nouvelle paire est à
  compléter dans la boîte.
- Si une paire reste sans clic, l'alignement courant de cette paire
  (auto-align ou ajustement souris) est **préservé via `fallback_Hs`** au
  lieu de retomber sur l'identité — on peut donc ne recliquer qu'**une**
  paire problématique sans casser le reste de la mosaïque.
- Les matrices `NaN` retournées par OpenCV sur configurations dégénérées
  sont explicitement détectées et remontées en `RuntimeError` plutôt que
  silencieusement propagées.

### 3. Ajustement manuel direct

Une fois l'alignement automatique fait, chaque photo est un `PhotoItem`
indépendant sur le canevas, librement déplaçable.

| Action                          | Souris / clavier                         |
|---------------------------------|------------------------------------------|
| Sélectionner / déplacer photo   | Clic-glisser                             |
| Pivoter photo (1° par cran)     | **Shift + molette** (×10 avec Ctrl)      |
| Mettre à l'échelle photo        | **Alt + molette** (rapide avec Ctrl)     |
| Nudge sub-pixel                 | Flèches du clavier (×10 avec Shift)      |
| Réinitialiser photo sélectionnée| Touche `R`                               |
| Zoom de la vue                  | Molette nue                              |
| Panoramique de la vue           | Bouton du milieu, ou Espace + glisser    |

Le `sceneRect` se recalcule à chaque déplacement avec 50 % de marge, donc
la surface de travail est extensible sans limite. Le panneau latéral
affiche en temps réel les `tx, ty, rotation, échelle` de la photo
sélectionnée.

#### Ordre des couches

Le groupe **« Photos chargées — ordre des couches »** du panneau latéral
permet de choisir quelle photo apparaît au-dessus des autres dans les
zones de recouvrement, **à la fois sur le canevas et dans la mosaïque
exportée**. Convention : **haut de la liste = couche du dessus**.

- Glisser-déposer dans la liste, ou boutons **▲ Avancer / ▼ Reculer**.
- Le `Stitcher` parcourt les photos dans l'ordre de la liste : la 1ʳᵉ
  dépose ses pixels en premier, les suivantes ne remplissent que les
  zones encore vides. La photo « référence » (au sens du repère
  coordonnées, `Hs[ref_idx] = I`) n'a plus aucun traitement particulier
  pour l'empilage — elle peut être à n'importe quelle position de la
  liste sans changer la disposition géométrique.
- Lors d'un réordonnement, les positions géométriques sont préservées
  (chaque photo conserve son homographie). Les clics sauvegardés sont
  remis à zéro car les paires consécutives peuvent ne plus correspondre.

### 4. Photos → Rotation manuelle

Quand l'EXIF est absent ou faux et qu'une photo est à 90° du bon sens :

- *Pivoter la sélection ↻ 90°* (`Ctrl+R`)
- *Pivoter la sélection ↺ 90°* (`Ctrl+Shift+R`)
- *Pivoter la sélection 180°*
- *Pivoter toutes les photos ↻ 90°* / ↺ 90°

La rotation est **destructive** sur le bitmap de la vignette ;
`images_data[i]["user_rotation_deg"]` mémorise le cumul, et
`ImageLoader.reload_full_res` la réapplique au moment du stitching
pleine résolution.

### 5. Référence → Définir comme référence

Construit la mosaïque pleine résolution à partir des positions courantes
(auto-align + manipulations souris) et la mémorise dans
`self.reference_mosaic`. Nécessaire avant toute comparaison.

### 6. Comparaison

- *Comparaison → Charger un PCB inspecté (image)…* : charge un fichier
  image déjà assemblé.
- *Comparaison → Charger des photos d'un PCB inspecté…* : prend un
  lot de photos, les aligne et les assemble automatiquement.
- *Comparaison → Lancer la comparaison* (`F5`) :
  1. Registration ECC de l'inspecté sur la référence (`cv2.findTransformECC`).
  2. Égalisation d'éclairage par CLAHE sur le canal L de LAB.
  3. Diff combinée : différence chromatique (`a`, `b`) + différence
     structurelle (SSIM inversé) sur la luminance.
  4. Seuillage Otsu + morphologie pour obtenir un masque propre.
  5. Extraction des composantes connexes → liste de `Defect` triés par
     sévérité (mélange aire relative + intensité moyenne).
- Le canevas affiche la référence avec un voile rouge sur les défauts et
  des bbox colorées vert→rouge selon la sévérité.
- La liste latérale est cliquable : cliquer un défaut cadre la vue
  dessus.

### 7. Export

- *Fichier → Exporter la mosaïque (JPEG)…*
- *Comparaison → Exporter l'overlay des défauts…*
- *Comparaison → Exporter le rapport JSON…*

Le JSON contient `{n_defects, defects: [{id, bbox, centroid, area_px,
severity, mean_diff}, ...]}`.

---

## Architecture du code

```
pcb-mosaic-maker/
├── run.py                       Point d'entrée (lance MainWindow)
├── pcbmosaic.spec               Spec PyInstaller (build du .exe)
├── build.ps1                    Script PowerShell de build Windows
├── requirements.txt             Dépendances runtime
├── requirements-dev.txt         Dépendances dev (pyinstaller, pytest)
├── CHANGELOG.md                 Historique par version
├── pcbmosaic/
│   ├── __init__.py
│   ├── core/                    Logique métier (sans Qt)
│   │   ├── loader.py            ImageLoader : EXIF, downscale, reload_full_res
│   │   ├── aligner.py           Aligner : phase / sift / orb / align_from_clicks
│   │   ├── stitcher.py          Stitcher : canvas, warp, blend
│   │   ├── exporter.py          Exporter : sauvegarde JPEG
│   │   └── comparator.py        Comparator : ECC + diff LAB + SSIM + défauts
│   ├── gui/                     Couche Qt
│   │   ├── main_window.py       MainWindow : actions, menus, slots
│   │   ├── canvas_view.py       CanvasView + PhotoItem (manipulation directe)
│   │   ├── tools_panel.py       Panneau latéral droit
│   │   └── click_align_dialog.py ClickAlignDialog (alignement assisté)
│   └── tests/
│       ├── test_stitcher.py
│       ├── test_aligner_phase.py
│       ├── test_aligner_clicks.py    Aligner.align_from_clicks (translation,
│       │                              chaînage, rotation, fallback_Hs, dégénéré)
│       └── test_comparator.py
└── examples/
    └── 20250427_*.jpg           4 photos d'exemple
```

`run.py` installe un `sys.excepthook` global qui écrit toute exception
non gérée dans `pcbmosaic-error.log` (à côté de `run.py` ou du `.exe`
PyInstaller). Précieux pour diagnostiquer un crash de la version
packagée sans console.

### Rôle de chaque module

**`core/loader.py`** — `ImageLoader.load(paths)` charge 2..20 fichiers,
applique l'orientation EXIF via `ImageOps.exif_transpose`, downscale en
vignette (max 2048 px), renvoie une liste de dict `{path, image, meta,
scale, user_rotation_deg}`. `load_more(paths)` ajoute sans la borne
haute. `reload_full_res(path, user_rotation_deg)` recharge un fichier
en pleine résolution et applique l'EXIF + la rotation utilisateur.

**`core/aligner.py`** — `Aligner(detector=...)` avec :

- `align(images)` : entrée publique. Dispatche selon le mode.
- `_align_phase(images)` : `cv2.phaseCorrelate` par paires successives
  avec fenêtre de Hann. Translation uniquement. Chaîne vers la photo
  centrale.
- `_align_features(images)` : SIFT ou ORB + BFMatcher (L2 ou Hamming) +
  ratio test de Lowe + RANSAC, homographie complète. Lève une exception
  si moins de 6 matches valides.
- `align_from_clicks(images, pair_clicks, fallback_Hs=None)` (statique) :
  pour chaque paire `(k, k+1)`, calcule une similarité 2×3 via
  `cv2.estimateAffinePartial2D(src=points_dans_k+1, dst=points_dans_k,
  method=cv2.RANSAC, ransacReprojThreshold=5.0)`. Chaîne vers la photo
  centrale.
  - Validation préalable : l'étalement des points cliqués doit être
    > 1 px dans chaque image, sinon `RuntimeError` immédiate.
  - Le résultat `M` est testé contre `np.any(np.isnan(M))` (OpenCV peut
    renvoyer une matrice de NaN sur configuration dégénérée), levée
    explicite plutôt que propagation silencieuse.
  - `fallback_Hs` : pour les paires sans clic suffisant, la relation
    relative `rel[k+1] = inv(H[k]) @ H[k+1]` est dérivée du fallback,
    préservant ainsi l'alignement courant de cette paire au lieu de
    retomber sur l'identité.

**`core/stitcher.py`** — `Stitcher.stitch(images, Hs, scale)` :

1. `_compute_canvas` : calcule la taille du canvas et la matrice de
   translation pour englober toutes les images warpées.
2. Warp chaque image avec `cv2.warpPerspective(INTER_LINEAR)` puis seuil
   binaire pour le masque.
3. Stratégie courante : *premier arrivé, premier servi*. **L'ordre de
   `images` détermine l'ordre des couches** : `images[0]` est la couche
   la plus en avant (ses pixels sont posés en premier), `images[1]`
   remplit ensuite les zones encore vides, etc. Plus aucun traitement
   particulier de la photo « référence » : son rôle est uniquement de
   fixer le repère de coordonnées (`Hs[ref_idx] = I`), pas l'empilage.
   Un mode `multiband` Laplacien est codé mais pas branché —
   **pourrait être activé dans une future version**.

**`core/comparator.py`** — `Comparator.compare(reference, inspected)` :

1. `_register` : `cv2.findTransformECC` (mode homographie) pour aligner
   l'inspecté sur la référence ; fallback ORB en cas d'échec.
2. `_diff_map` : convertit les deux en LAB, applique CLAHE sur L,
   calcule `|Δa|+|Δb|` (chrominance) et `1 − SSIM(L)` (structure),
   combine en `0.55·struct + 0.45·chroma`.
3. `_binarize` : seuillage Otsu (ou seuil fixe) + ouverture/fermeture
   morphologique.
4. `_extract_defects` : `cv2.connectedComponentsWithStats` → liste de
   `Defect(id, bbox, centroid, area_px, severity, mean_diff)` triés
   par sévérité décroissante.
5. `render_overlay(reference, result)` (statique) : compose un voile
   rouge sur les défauts + bbox colorées vert→rouge.

**`gui/canvas_view.py`** — `CanvasView(QGraphicsView)` + `PhotoItem`
(`QGraphicsPixmapItem`). Le PhotoItem porte sa propre `_H_initial` plus
les manipulations utilisateur (`pos`, `rotation`, `scale`). Méthodes
clés :

- `prepare_items(images, Hs_thumb)` : pose une PhotoItem par photo,
  attribue le `Z-value` selon la position dans la liste pour matérialiser
  l'**ordre des couches** (`images[0]` au-dessus de `images[1]`, etc.).
- `current_homographies()` : lit `sceneTransform()` de chaque item →
  matrice 3×3 utilisée par le stitcher pleine résolution.
- `selected_index()` / `replace_photo_image(idx, new_bgr)` : utilisés
  par les actions de rotation pour mettre à jour le bitmap d'une
  photo sans casser sa position scénique.
- `set_compare_overlay(overlay, result)` + `focus_defect(id)` : mode
  comparaison.

**`gui/tools_panel.py`** — `ToolsPanel(QWidget)` : sections résolution
de sortie / mode d'alignement / liste des photos / manipulation /
défauts. La liste des photos est **réordonnable** par glisser-déposer
ou via les boutons ▲ Avancer / ▼ Reculer ; chaque changement émet
`photoOrderChanged(List[str])` (les chemins dans le nouvel ordre).

**`gui/main_window.py`** — `MainWindow` orchestre tout. État stocké
dans `self.images_data` (liste de dict du loader), `self.homographies`,
`self.reference_mosaic`, `self.inspected_mosaic`, `self.compare_result`,
et `self.saved_pair_clicks` (correspondances persistantes du dialog
d'alignement par clics). Slot `_on_photo_order_changed` synchronise
`images_data` et `homographies` quand l'utilisateur réordonne la liste,
sans toucher à la disposition géométrique du canvas.

**`gui/click_align_dialog.py`** — `ClickAlignDialog(QDialog)` avec deux
`_ClickableView` côte à côte. Maintient pour chaque paire d'images une
liste `_clicks[k]` de tuples `('A'|'B', x, y)` dans l'ordre de saisie.
Affiche des marqueurs numérotés colorés. Validation à la sortie :
**au moins 3 paires complètes par couple**. Accepte un paramètre
optionnel `initial_pair_clicks` pour pré-remplir le dialog avec des
correspondances déjà saisies (réouverture après ajout de photos par ex.).

---

## Lancer les tests

```bash
pip install pytest
python -m pytest pcbmosaic/tests/ -v
```

Couverture actuelle (11 tests) :

- `test_stitcher.py` :
  - `test_stitcher_minimal` — 4 tuiles avec fond gris uni, vérifie que
    le canvas est entièrement rempli (> 99 % de pixels non noirs).
  - `test_stitcher_layer_order_first_wins` — deux tuiles superposées
    rouge/bleu, verrouille la sémantique « première de la liste =
    couche du dessus ».
- `test_aligner_phase.py` — 3 vues d'une même texture, vérifie que la
  phase correlation retrouve les translations (tx < 0 à gauche, tx > 0
  à droite).
- `test_aligner_clicks.py` — `Aligner.align_from_clicks` :
  - translation pure (2 images),
  - chaînage sur 3 images,
  - rotation + échelle (4 points, rotation 15°, scale 1.1),
  - `fallback_Hs` préserve l'alignement d'une paire sans clic,
  - absence de fallback retombe sur l'identité (comportement historique),
  - configuration dégénérée (points concentrés) → `RuntimeError`.
- `test_comparator.py` — PCB synthétique avec composant manquant et
  composant en trop, vérifie que les 2 défauts sont détectés et triés
  par sévérité ; `render_overlay` n'altère pas la référence.

---

## Limites connues + pistes pour la suite

### Algorithmiques

- **Stitcher** : pas de multiband blending actif → coutures visibles si
  les expositions diffèrent. Le code Laplacien existe (`_multiband_blend`)
  mais n'est pas appelé. À brancher avec un budget mémoire.
- **Aligner phase** : ne gère que la translation. Si une photo a une
  vraie rotation par rapport aux voisines, il faut passer en SIFT ou en
  alignement par clics. Une extension log-polar pourrait gérer la
  rotation automatiquement.
- **Aligner SIFT/ORB** : peu fiable sur les PCB répétitifs (composants
  identiques, vias en grille). Le ratio test à 0.75 calibré pour SIFT
  est trop strict pour ORB (Hamming) — devrait passer à 0.80–0.85 en
  mode ORB.
- **Comparator** : suppose que référence et inspecté sont à des échelles
  voisines. Si le cadrage diffère beaucoup, ECC ne converge pas ; le
  fallback ORB peut bavurer. Une étape de mise à l'échelle initiale par
  features serait bienvenue.

### UX

- Pas de wizard guidé étapes par étape. Les menus marchent, mais un
  utilisateur métier nouveau peut se perdre.
- Pas de thème personnalisé (look Qt par défaut). Une charte type
  `qt-material` Fluent améliorerait beaucoup la perception.
- Pas d'export d'un rapport HTML autonome partageable sur mobile.
- Pas d'annotations manuelles supplémentaires sur la mosaïque (l'ancien
  monolithe HTML les avait, mais elles n'ont pas été portées).
- Pas de calibration mm/pixel propagée au rapport.

### Distribution

- Le `.exe` PyInstaller pèse ~150 MB. Nuitka donnerait ~80–120 MB et un
  démarrage plus rapide. Pas critique pour un outil métier interne.
- Pas de signature Authenticode → Windows SmartScreen affiche un
  avertissement la première fois.

---

## Branches Git

- **`main`** : version historique (Python Qt 0.1, sans comparateur ni
  alignement par clics).
- **`claude/python-to-html-conversion-kh3MO`** : branche active. C'est
  ici que vivent toutes les fonctionnalités 0.2.x (assemblage moderne,
  comparateur, manipulation directe, alignement par clics, rotations).
  Le fichier `pcb-mosaic-maker.html` est conservé pour l'historique
  mais **n'est plus maintenu** — la version HTML/OpenCV.js a été
  abandonnée pour cause de plafond mémoire WASM et d'absence de SIFT
  dans le build CDN.

---

## Pour Claude Code / agents qui reprennent

Points d'entrée typiques selon la tâche :

| Tâche                                           | Fichier à toucher en premier              |
|-------------------------------------------------|-------------------------------------------|
| Nouveau mode d'alignement                       | `pcbmosaic/core/aligner.py`               |
| Améliorer la qualité du blending                | `pcbmosaic/core/stitcher.py`              |
| Changer l'ordre / le z-order des photos         | `pcbmosaic/gui/tools_panel.py` (réorder) + `pcbmosaic/gui/canvas_view.py` (Z) + `pcbmosaic/core/stitcher.py` (empilage) |
| Changer la détection de défauts                 | `pcbmosaic/core/comparator.py`            |
| Ajouter une action menu / un raccourci          | `pcbmosaic/gui/main_window.py`            |
| Modifier le dialog d'alignement par clics       | `pcbmosaic/gui/click_align_dialog.py`     |
| Modifier l'interaction sur le canevas           | `pcbmosaic/gui/canvas_view.py`            |
| Ajouter un widget dans le panneau latéral       | `pcbmosaic/gui/tools_panel.py`            |
| Changer la procédure de build                   | `pcbmosaic.spec`, `build.ps1`             |
| Ajouter / modifier des tests                    | `pcbmosaic/tests/`                        |

Conventions du projet :

- Code en français pour les chaînes affichées (UI, messages d'erreur,
  commentaires longs). Identifiants et docstrings courts en anglais
  OK si ça reste cohérent dans le fichier.
- Pas de dépendances supplémentaires sans mise à jour de
  `requirements.txt`.
- Tests dans `pcbmosaic/tests/`, nom `test_*.py`, fonctions `test_*`.
- L'API publique des modules `core/` reste **sans Qt** pour pouvoir
  être testée et réutilisée hors GUI.

Quand tu fais évoluer le projet, mets à jour le `CHANGELOG.md` (sous
*[unreleased]* ou directement sous une nouvelle version) avant de
commit.
