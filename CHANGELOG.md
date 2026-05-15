# Changelog

Toutes les modifications notables sont consignées ici. Le format suit
[Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).

## [unreleased]

### Ajouté — Ordre des couches contrôlable

Le groupe **« Photos chargées — ordre des couches »** du panneau latéral
permet de choisir quelle photo apparaît au-dessus dans les zones de
recouvrement (canvas **et** mosaïque exportée), à la façon des calques d'un
éditeur d'image :

- **Glisser-déposer** un nom dans la liste pour le déplacer.
- Boutons **▲ Avancer / ▼ Reculer** pour un déplacement pas à pas de la
  photo sélectionnée.
- **Haut de la liste = couche du dessus** (ses pixels sont placés en
  premier, et les couches suivantes ne remplissent que ce qui est encore
  vide).

Changements techniques :

- `PhotoItem.setZValue` est calculé sur `(total − 1 − idx) × 0.001` au
  lieu de `idx × 0.001`, pour que `images[0]` apparaisse devant
  `images[1]`, etc.
- `Stitcher.stitch` n'a plus de traitement particulier pour la photo
  « référence » : il parcourt désormais les photos dans l'ordre de la
  liste, ce qui rend l'ordre des couches déterministe et contrôlable par
  l'utilisateur.
- Lors d'un réordonnement, la disposition géométrique sur le canvas
  reste inchangée (chaque photo garde son homographie courante). Les
  clics de l'alignement par clics sont remis à zéro car les paires
  consécutives peuvent ne plus exister.
- Nouveau test `test_stitcher_layer_order_first_wins` qui verrouille la
  sémantique : pour deux tuiles superposées, celle qui est en tête de
  liste domine l'autre dans le rendu final.

### Ajouté — Persistance des clics de l'alignement par clics

- Les correspondances cliquées sont désormais **mémorisées** dans
  `MainWindow.saved_pair_clicks`. Rouvrir **Référence → Aligner par clics**
  réaffiche immédiatement les points précédemment placés (marqueurs
  numérotés colorés), prêts à être ajustés ou complétés.
- Quand l'utilisateur **ajoute une photo** après un alignement par clics :
  les paires déjà cliquées sont conservées, et les nouvelles paires (entre
  la dernière photo existante et les nouvelles) apparaissent vides dans le
  dialogue, à compléter au besoin.
- Si une paire reste sans clic au moment de valider, l'alignement courant
  de cette paire (auto-phase ou ajustement souris) est **préservé via le
  paramètre `fallback_Hs`** au lieu de retomber sur l'identité.
  Conséquence pratique : on peut ne recliquer **que** la paire qui pose
  problème sans casser le reste de la mosaïque.

### Corrigé — Ajout d'une photo écrasait l'alignement existant

Auparavant, **Fichier → Ajouter des photos** relançait l'alignement
automatique sur **toutes** les photos depuis zéro, ce qui annulait le
travail de l'utilisateur (alignement par clics, ajustements souris).

Nouveau comportement : les photos existantes et leurs positions sont
**préservées telles quelles**. Chaque nouvelle photo est alignée par paire
successive avec la précédente, et son homographie est chaînée vers le
repère global déjà établi. L'utilisateur peut ainsi composer une mosaïque
progressivement, photo par photo, sans perdre son travail.

En cas d'échec de l'alignement automatique sur une nouvelle photo, un
rollback complet est effectué : l'état d'avant ajout est restauré.

### Corrigé — `dlg.Accepted` en PySide6 récent

Dans les versions modernes de PySide6, `Accepted` est un membre d'enum de
la classe `QDialog` et non un attribut d'instance — `dlg.Accepted` lève
`AttributeError`. Remplacé par `QDialog.Accepted` dans
`MainWindow.run_click_align()`.

### Ajouté — Logger d'exceptions global

`run.py` installe un `sys.excepthook` qui écrit tout traceback non géré
dans `pcbmosaic-error.log` (à côté de `run.py` ou du `.exe` PyInstaller).
Permet de diagnostiquer un crash de l'application packagée sans console.

### Corrigé — Alignement par clics : résultats incorrects

- **Bug NaN silencieux.** `cv2.estimateAffinePartial2D` peut renvoyer une
  matrice remplie de `NaN` (et non `None`) lorsque les points cliqués sont
  dégénérés (toutes les correspondances au même endroit dans une image).
  L'ancien `if M is None: continue` laissait ces `NaN` se propager dans
  toute la chaîne → toutes les homographies devenaient `NaN` → les images
  étaient mal positionnées sans aucun message d'erreur.
  Corrigé : détection explicite des `NaN` + levée d'une `RuntimeError`
  descriptive qui remonte jusqu'au dialogue d'erreur Qt.
- **Méthode LMEDS remplacée par RANSAC.** LMEDS est conçu pour les grands
  jeux de points ; avec 3–5 points cliqués, RANSAC est plus robuste et
  déterministe.
- **Minimum 3 paires par couple d'images** (au lieu de 2). Avec 3 points
  bien espacés, translation + rotation + échelle sont déterminées même si
  un clic est légèrement imprécis. Le dialogue met à jour son compteur en
  temps réel (vert = OK, orange = insuffisant).
- **Validation préalable de l'étalement des points** : si tous les points
  cliqués dans l'une des images sont à moins de 1 px les uns des autres,
  une erreur explicite est déclenchée avant même d'appeler OpenCV.

### Ajouté

- `pcbmosaic/tests/test_aligner_clicks.py` : 4 tests unitaires couvrant
  translation pure (2 images), chaînage sur 3 images, rotation + échelle,
  et cas dégénéré.

### Corrigé — Test stitcher

- `test_stitcher_minimal` : les tuiles synthétiques avaient un fond **noir**,
  ce qui rendait l'assertion « 99 % de pixels non-noirs » impossible à
  satisfaire (seuls les cercles couvrent ~62 % du canvas). Les tuiles ont
  maintenant un fond **gris uni (180)** ; le test vérifie correctement que
  le stitcher remplit tout le canvas.

## [0.2.3] — 2026-05-08

### Corrigé — Orientation EXIF + chargement multi-dossier

- **Photos affichées tournées de 90°.** Le `ImageLoader` utilise désormais
  `PIL.ImageOps.exif_transpose`, la méthode officielle qui gère
  correctement les 8 valeurs de la balise Orientation. L'ancienne
  approche manuelle souffrait de cas limites (orientations 5/7/8) et de
  certaines images sans EXIF.
- **Impossible de mélanger des photos de plusieurs dossiers.** Nouvelle
  action **Fichier → Ajouter des photos…** (`Ctrl+Shift+O`) qui complète
  la sélection courante au lieu de la remplacer. À utiliser plusieurs
  fois pour piocher dans des dossiers différents. L'alignement est
  relancé automatiquement sur l'ensemble.
- **Plafond passé de 10 à 20 photos** dans `ImageLoader.load`.
- **Rotation manuelle quand l'EXIF est absent ou faux.** Nouveau menu
  **Photos** :
  - *Pivoter la sélection ↻ 90°* (`Ctrl+R`)
  - *Pivoter la sélection ↺ 90°* (`Ctrl+Shift+R`)
  - *Pivoter la sélection 180°*
  - *Pivoter toutes les photos ↻ 90°* / ↺ 90°
  La rotation est **destructive** sur le bitmap (vignette + plein-res au
  prochain chargement), donc elle se propage au dialog d'alignement par
  clics et à l'export. Le champ `user_rotation_deg` est mémorisé pour
  que `_stitch_full_res` ré-applique la rotation au moment de relire le
  fichier d'origine en pleine résolution.

## [0.2.2] — 2026-05-08

### Ajouté — Alignement assisté par clics

L'alignement automatique (phase / SIFT / ORB) reste fragile sur des photos
de PCB. On ajoute donc un mode infaillible : l'utilisateur clique lui-même
les correspondances entre paires consécutives.

- Nouveau menu : **Référence → Aligner par clics…** (raccourci `Ctrl+L`).
- Nouveau dialog `ClickAlignDialog` : deux photos côte à côte, on alterne
  les clics GAUCHE puis DROITE pour ajouter une paire de points
  correspondants. Marqueurs numérotés et colorés sur les deux vues.
- Navigation entre paires : ← / → ou `PgUp` / `PgDown`. Annuler dernier
  point : `Ctrl+Z`. Recommencer la paire courante. Zoom à la molette,
  panoramique au bouton du milieu sur chaque vue.
- Estimation par similarité (translation + rotation + échelle uniforme)
  via `cv2.estimateAffinePartial2D` en LMEDS, robuste aux clics
  approximatifs. Minimum 2 paires de points par couple d'images.
- Nouvelle méthode statique `Aligner.align_from_clicks(images,
  pair_clicks)`. Chaînage vers l'image de référence centrale, même
  convention que les autres modes.
- Une fois l'alignement appliqué, les photos repartent dans le canevas
  comme objets librement déplaçables — tu peux peaufiner à la souris
  par-dessus si besoin.

## [0.2.1] — 2026-05-08

### Modifié — Ergonomie de l'ajustement manuel

L'ancien système « image fantôme semi-transparente + flèches clavier » est
remplacé par de la **manipulation directe** de chaque photo, à la souris :

- Chaque photo devient un objet (`PhotoItem`) du canevas, librement
  déplaçable au **clic-glisser**, avec un cadre cyan de sélection.
- **Shift + molette** = rotation de la photo sélectionnée autour de son
  centre (1° par cran, ×10 avec Ctrl).
- **Alt + molette** = redimensionnement (×0,98 / 1,02 par cran, plus
  rapide avec Ctrl).
- **Molette nue** = zoom de la vue (centré sur le curseur).
- **Bouton du milieu** ou **Espace + glisser** = panoramique de la vue.
- **Flèches clavier** = nudge fin (1 px ou 10 px avec Shift) sur la photo
  sélectionnée.
- **R** = réinitialise les manipulations utilisateur sur la photo
  sélectionnée (revient à la position auto-align).
- Bouton **« Réinitialiser les positions »** dans le panneau latéral pour
  tout remettre d'un coup.
- **Surface de travail extensible** : le `sceneRect` se recalcule à
  chaque déplacement avec 50 % de marge, donc les photos peuvent être
  poussées arbitrairement loin sans perdre la zone de travail.
- **Affichage live** des `tx, ty, rotation, échelle` de la photo
  sélectionnée dans le panneau latéral, et synchronisation bidirectionnelle
  entre la liste des photos et la sélection sur le canevas.

L'API publique de `CanvasView` change : `prepare_items()` remplace le
couple `set_preview()` / `prepare_manual()` ; `current_homographies()`
remplace `final_homographies()`.

## [0.2.0] — 2026-05-08

Cette version pivote l'application vers son objectif métier réel : produire
une **image de référence** d'un PCB, puis **comparer d'autres exemplaires** à
cette référence pour faire ressortir les défauts. La version HTML reste dans
le repo mais n'est plus la cible de développement.

### Ajouté

- **`pcbmosaic/core/comparator.py`** — module complet de détection de défauts.
  - Registration ECC (`cv2.findTransformECC`) du PCB inspecté sur la
    référence, avec fallback ORB en cas d'échec.
  - Égalisation d'éclairage par CLAHE sur le canal L de LAB (insensibilise
    la diff aux variations d'expo / balance des blancs).
  - Diff combinée : différence chromatique (a, b) + différence structurelle
    (SSIM inversé) sur la luminance.
  - Seuillage Otsu (ou seuil fixe) + ouverture/fermeture morphologique pour
    obtenir un masque propre.
  - Extraction des composantes connexes → liste de `Defect` triés par
    sévérité (mélange aire relative + intensité moyenne).
  - `Comparator.render_overlay()` : voile rouge sur les défauts +
    bbox colorées par sévérité (vert → jaune → rouge).
- **Mode d'alignement « phase »** dans `Aligner`, basé sur
  `cv2.phaseCorrelate` par paires successives, sub-pixel et robuste sur les
  PCB peu texturés. C'est désormais le mode par défaut.
- **GUI**
  - Onglet « Comparaison » dans `ToolsPanel` : liste cliquable des défauts
    triés par sévérité, avec badge de couleur.
  - Sélecteur de mode d'alignement (`phase` / `sift` / `orb`).
  - Menu **Référence** → « Définir comme référence » (assemblage pleine
    résolution stocké en mémoire).
  - Menu **Comparaison** : charger un PCB inspecté (image déjà assemblée
    OU série de photos à assembler), lancer la comparaison, exporter
    l'overlay et le rapport JSON.
  - `CanvasView.set_compare_overlay()` + `focus_defect()` : affiche
    l'overlay des défauts et zoome automatiquement sur le défaut cliqué.
- **Packaging Windows**
  - `run.py` : point d'entrée unique.
  - `pcbmosaic.spec` : spec PyInstaller `--onefile --windowed` avec
    exclusions Qt (WebEngine, Multimedia, Charts, 3D, Bluetooth…) pour
    descendre le binaire à ~150 MB.
  - `build.ps1` : script PowerShell qui installe PyInstaller au besoin
    et produit `dist/PCB-Mosaic-Maker.exe`.
  - `requirements-dev.txt` : pyinstaller + pytest.
- **Tests**
  - `test_aligner_phase.py` : vérifie que la phase correlation retrouve
    une translation connue sur 3 vues synthétiques.
  - `test_comparator.py` : injecte un composant manquant et un composant en
    trop, vérifie qu'ils sont détectés et que les défauts sortent triés
    par sévérité.

### Modifié

- **`MainWindow`** entièrement refactorisée pour porter le workflow
  Référence → Inspection → Comparaison → Export. Les anciennes actions
  Ouvrir / Exporter restent disponibles.
- **`Aligner`** garde la même API publique mais accepte un nouveau mode
  `detector="phase"` ; le constructeur tombe gracieusement sur ORB si
  SIFT n'est pas disponible.
- **`CanvasView`** : trois modes d'affichage cohabitent (preview, overlay
  manuel, overlay de comparaison) sans interférence.

### À faire pour 0.3 (pistes)

- Wizard UI 4 étapes (Référence / Inspection / Comparaison / Export) en
  remplacement du panneau latéral dense.
- Charte graphique (qt-material ou QSS Fluent-like).
- Export d'un rapport HTML autonome (mosaïque + annotations cliquables) à
  partager sur mobile, sans dépendance OpenCV.js.
- Filtrage interactif des défauts par sévérité / surface dans la liste.
- Calibration mm/pixel propagée aux mesures de bbox dans le rapport.

---

## [0.1.0] — initial

Version Python Qt avec assemblage par SIFT/ORB + RANSAC, blending par
collage séquentiel, ajustement manuel par overlay opacité + flèches /
molette, export JPEG.
