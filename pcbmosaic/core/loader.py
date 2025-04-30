from __future__ import annotations
import pathlib
from typing import List, Dict, Tuple

import cv2
import numpy as np
from PIL import Image, ExifTags


class ImageLoader:
    """Charge les images et renvoie (img_BGR, meta) pour chacune."""

    def __init__(self, max_size: Tuple[int, int] | None = (2048, 2048)):
        self.max_size = max_size
        # Mappe les clés EXIF à un nom lisible
        self._exif_map = {v: k for k, v in ExifTags.TAGS.items()}

    # ------------------------------------------------------------------ #
    def _pil_to_bgr(self, pil_img: Image.Image) -> np.ndarray:
        """Pillow RGB ➜ NumPy BGR"""
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    # ------------------------------------------------------------------ #
    def load(self, paths: List[str | pathlib.Path]) -> List[Dict]:
        if not 2 <= len(paths) <= 10:
            raise ValueError("Il faut sélectionner entre 2 et 10 images.")

        loaded = []
        for p in map(pathlib.Path, paths):
            pil = Image.open(p)
            orig_w, orig_h = pil.size          # NEW  original size
            meta = {self._exif_map.get(k, k): v for k, v in pil.getexif().items()}

            # Rotation automatique si orientation EXIF disponible
            orient = meta.get("Orientation", 1)
            pil = ImageLoader._apply_orientation(pil, orient)

            # downscale pour preview / alignement
            if self.max_size:
                pil.thumbnail(self.max_size, Image.Resampling.LANCZOS)

            scale = pil.size[0] / orig_w       # NEW  (ratio = vignettes / full-res)

            loaded.append(
                {
                    "path": str(p),
                    "image": self._pil_to_bgr(pil),
                    "meta": meta,
                    "scale": scale,            # NEW
                }
            )
        return loaded

    # ------------------------------------------------------------------ #
    @staticmethod
    def _apply_orientation(img: Image.Image, orientation: int) -> Image.Image:
        """Applique la rotation EXIF (1 = rien)."""
        METHOD = {
            2: Image.FLIP_LEFT_RIGHT,
            3: Image.ROTATE_180,
            4: Image.FLIP_TOP_BOTTOM,
            5: Image.TRANSPOSE,
            6: Image.ROTATE_270,
            7: Image.TRANSVERSE,
            8: Image.ROTATE_90,
        }
        if orientation in METHOD:
            return img.transpose(METHOD[orientation])
        return img
