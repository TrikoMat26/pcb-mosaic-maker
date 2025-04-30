from __future__ import annotations
import cv2
import pathlib


class Exporter:
    """Gère la sauvegarde JPEG haut débit."""

    def __init__(self, quality: int = 95):
        self.quality = int(max(70, min(100, quality)))

    # ------------------------------------------------------------------ #
    def save(self, img, path: str | pathlib.Path, quality: int | None = None):
        q = int(max(70, min(100, quality if quality is not None else self.quality)))
        ok = cv2.imwrite(str(path), img, [cv2.IMWRITE_JPEG_QUALITY, q])
        if not ok:
            raise IOError(f"Impossible de sauvegarder {path}")
