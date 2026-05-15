"""
ImageLoader
~~~~~~~~~~~
Charge un lot de photos (2..20) et renvoie pour chacune :

    {
        "path": str,                  # chemin absolu
        "image": np.ndarray (BGR),    # vignette redimensionnée + orientée
        "meta": dict,                 # tags EXIF lisibles
        "scale": float,               # ratio vignette / plein écran (largeur)
        "user_rotation_deg": int      # rotation utilisateur cumulée (0/90/180/270)
    }

L'orientation EXIF est appliquée via ``PIL.ImageOps.exif_transpose`` —
c'est la méthode officielle de Pillow qui gère correctement les 8 valeurs
de la balise Orientation. Les photos sans EXIF restent dans l'orientation
brute des pixels ; l'utilisateur peut alors pivoter manuellement depuis
le menu ``Photos`` de l'application.
"""
from __future__ import annotations

import pathlib
from typing import Dict, List, Tuple

import cv2
import numpy as np
from PIL import ExifTags, Image, ImageOps


# Constantes
MIN_IMAGES = 2
MAX_IMAGES = 20


class ImageLoader:
    """Charge les images, applique l'EXIF, downscale pour le preview."""

    def __init__(self, max_size: Tuple[int, int] | None = (2048, 2048)):
        self.max_size = max_size
        self._exif_map = {v: k for k, v in ExifTags.TAGS.items()}

    # ------------------------------------------------------------------ #
    @staticmethod
    def apply_exif_orientation(img: Image.Image) -> Image.Image:
        """Applique l'orientation EXIF de manière robuste (toutes les valeurs)."""
        try:
            return ImageOps.exif_transpose(img)
        except Exception:
            return img

    # Ancien nom conservé pour compatibilité ascendante
    @staticmethod
    def _apply_orientation(img: Image.Image, orientation: int = 1) -> Image.Image:
        return ImageOps.exif_transpose(img) if img is not None else img

    # ------------------------------------------------------------------ #
    def _pil_to_bgr(self, pil_img: Image.Image) -> np.ndarray:
        """Pillow RGB ➜ NumPy BGR."""
        if pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    # ------------------------------------------------------------------ #
    def load(self, paths: List[str | pathlib.Path]) -> List[Dict]:
        """Charge une liste de fichiers et renvoie les dictionnaires décrits."""
        if not MIN_IMAGES <= len(paths) <= MAX_IMAGES:
            raise ValueError(
                f"Il faut entre {MIN_IMAGES} et {MAX_IMAGES} images "
                f"(reçu {len(paths)})."
            )
        return [self._load_one(p) for p in paths]

    def load_more(self, paths: List[str | pathlib.Path]) -> List[Dict]:
        """Charge un lot complémentaire (au moins 1 fichier, pas de borne haute)."""
        if not paths:
            raise ValueError("Aucun fichier à ajouter.")
        return [self._load_one(p) for p in paths]

    # ------------------------------------------------------------------ #
    def _load_one(self, path: str | pathlib.Path) -> Dict:
        p = pathlib.Path(path)
        pil = Image.open(p)

        # Récupère le tag Orientation AVANT exif_transpose (pour la trace meta)
        try:
            exif = pil.getexif() or {}
        except Exception:
            exif = {}
        meta = {self._exif_map.get(k, k): v for k, v in exif.items()}

        orig_w, orig_h = pil.size
        # Applique l'orientation EXIF de manière robuste
        pil = self.apply_exif_orientation(pil)

        # Downscale pour l'affichage / l'alignement
        if self.max_size:
            pil.thumbnail(self.max_size, Image.Resampling.LANCZOS)

        # Le ratio se calcule par rapport à la dimension la plus grande,
        # robuste aux rotations 90° qui inversent W et H.
        new_w, new_h = pil.size
        scale = max(new_w, new_h) / max(orig_w, orig_h)

        return {
            "path": str(p),
            "image": self._pil_to_bgr(pil),
            "meta": meta,
            "scale": scale,
            "user_rotation_deg": 0,
        }

    # ------------------------------------------------------------------ #
    @staticmethod
    def reload_full_res(path: str | pathlib.Path, user_rotation_deg: int = 0) -> np.ndarray:
        """
        Recharge un fichier en pleine résolution, applique l'EXIF puis la
        rotation utilisateur. Utilisé par le stitcher pour l'export final.
        """
        pil = Image.open(path)
        pil = ImageOps.exif_transpose(pil)
        if pil.mode != "RGB":
            pil = pil.convert("RGB")
        img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
        if user_rotation_deg % 360 == 90:
            img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        elif user_rotation_deg % 360 == 180:
            img = cv2.rotate(img, cv2.ROTATE_180)
        elif user_rotation_deg % 360 == 270:
            img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return img
