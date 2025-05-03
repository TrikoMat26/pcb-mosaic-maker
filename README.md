# PCB-Mosaic-Maker

Petit utilitaire Qt qui assemble de 2 à 10 photos partiellement recouvrantes d’un PCB en une image **JPEG haute définition**.

## Installation rapide

```bash
pip install -r requirements.txt
python -m pcbmosaic.gui.main_window


# PCB-Mosaic-Maker : Un outil d'assemblage d'images de circuits imprimés

PCB-Mosaic-Maker est un utilitaire développé en Python qui permet d'assembler de 2 à 10 photos partiellement recouvrantes d'un circuit imprimé (PCB) en une seule image JPEG haute définition[2]. Ce programme utilise des technologies avancées de traitement d'image pour créer des mosaïques de PCB de haute qualité.

## Architecture et fonctionnalités

L'application est structurée en deux modules principaux :

**Module Core :**
- **Loader** : Gère le chargement des images et prend en charge les métadonnées EXIF
- **Aligner** : Utilise des algorithmes de vision par ordinateur (SIFT ou ORB) pour détecter automatiquement les points communs entre les images
- **Stitcher** : Assemble les images grâce aux homographies calculées et peut utiliser différentes techniques de fusion
- **Exporter** : S'occupe de la sauvegarde au format JPEG avec contrôle de la qualité

**Interface utilisateur :**
- **Canvas View** : Zone d'affichage interactive permettant la manipulation des images
- **Tools Panel** : Panneau de contrôle pour ajuster les paramètres et sélectionner les images
- **Main Window** : Fenêtre principale intégrant tous les composants

## Processus d'utilisation

1. **Chargement** : L'utilisateur sélectionne 2 à 10 photos de PCB partiellement recouvrantes
2. **Alignement automatique** : Le programme analyse les images pour déterminer les points communs et calculer les transformations géométriques nécessaires
3. **Ajustement manuel** : L'utilisateur peut affiner l'alignement par des déplacements, rotations ou mises à l'échelle précises
4. **Exportation** : La mosaïque finale est générée en haute résolution et exportée au format JPEG

## Caractéristiques techniques

- **Détection de caractéristiques** : Utilise SIFT (Scale-Invariant Feature Transform) ou ORB (Oriented FAST and Rotated BRIEF) pour identifier les points caractéristiques des images
- **Homographie** : Calcule des matrices de transformation pour aligner précisément les images
- **Fusion multi-bandes** : Technique avancée qui minimise les artefacts visuels aux jonctions entre les images
- **Correction d'orientation** : Prend en compte les métadonnées EXIF pour l'affichage correct des images
- **Workflow à double résolution** : Utilise des versions basse résolution pour l'interface utilisateur et applique les transformations aux images haute résolution pour le rendu final

Ce programme est particulièrement utile pour les ingénieurs et techniciens en électronique qui ont besoin de visualiser des PCB complets en haute résolution, semblable aux services professionnels de fabrication de PCB personnalisés qui nécessitent des analyses détaillées du circuit avant production[2].
