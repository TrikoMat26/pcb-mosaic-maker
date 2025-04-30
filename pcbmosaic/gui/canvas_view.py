from __future__ import annotations
from typing import List
import numpy as np
import cv2

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPixmap, QImage, QWheelEvent, QPainter
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem


def cv2_to_qpix(img: np.ndarray) -> QPixmap:
    h, w = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    qimg = QImage(rgb.data, w, h, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg).copy()


class CanvasView(QGraphicsView):
    """Affiche la pré-mosaïque basse résolution + superposition “A/B switch”."""

    def __init__(self):
        super().__init__()
        self.setRenderHint(QPainter.Antialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.preview_item: QGraphicsPixmapItem | None = None
        self.overlay_item: QGraphicsPixmapItem | None = None

        self._zoom = 0

    # ------------------------------------------------------------------ #
    def set_preview(self, images: List[np.ndarray], Hs: List[np.ndarray]):
        """Reconstruit un aperçu basse résolution pour le canvas."""
        from ..core.stitcher import Stitcher

        preview = Stitcher(blend_mode="average").stitch(images, Hs, scale=0.25)
        pix = cv2_to_qpix(preview)

        self.scene.clear()
        self.preview_item = self.scene.addPixmap(pix)
        self.setSceneRect(self.scene.itemsBoundingRect())
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)
        self._zoom = 0

    # ------------------------ navigation zoom/pan --------------------- #
    def wheelEvent(self, event: QWheelEvent):
        if event.modifiers() & Qt.ControlModifier:
            delta = event.angleDelta().y()
            zoom_in = delta > 0
            factor = 1.25 if zoom_in else 0.8
            self._zoom += 1 if zoom_in else -1
            if self._zoom < -4:
                self._zoom = -4
                return
            if self._zoom > 10:
                self._zoom = 10
                return
            self.scale(factor, factor)
        else:
            super().wheelEvent(event)
