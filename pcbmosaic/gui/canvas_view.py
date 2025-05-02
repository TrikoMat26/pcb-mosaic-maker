from __future__ import annotations
from typing import List
import numpy as np, cv2
from math import cos, sin, radians

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QPixmap, QImage, QWheelEvent, QPainter, QTransform, QKeyEvent
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem

# ---- helper ----
def cv2_to_qpix(img: np.ndarray) -> QPixmap:
    h, w = img.shape[:2]
    rgb  = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    rgb  = np.ascontiguousarray(rgb)                  # s’assure d’un buffer compact
    bytes_per_line = 3 * w                            # *** nouvelle ligne ***
    qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg).copy()

class CanvasView(QGraphicsView):
    """Preview + overlay for manual fine‑tuning."""

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

        # manual‑align state
        self._images: list[np.ndarray] = []
        self._Hs_thumb: list[np.ndarray] = []
        self._deltas: list[np.ndarray] = []  # 3×3 homography delta per img
        self._current_idx: int | None = None
        self._alpha = 0.5

    # ------------------------------------------------------------------ #
    def set_preview(self, images: List[np.ndarray], Hs: List[np.ndarray]):
        from ..core.stitcher import Stitcher
        preview = Stitcher(blend_mode="average").stitch(images, Hs, scale=0.25)
        self.scene.clear()
        self.preview_item = self.scene.addPixmap(cv2_to_qpix(preview))
        self.setSceneRect(self.scene.itemsBoundingRect())
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)
        self._zoom = 0

    # ------------------------------------------------------------------ #
    def prepare_manual(self, images: List[np.ndarray], Hs_thumb: List[np.ndarray]):
        """Store full‑res thumbnails + initial homographies."""
        self._images = images
        self._Hs_thumb = Hs_thumb
        self._deltas = [np.eye(3) for _ in images]

    # -------------------- overlay management ------------------------- #
    def select_overlay(self, idx: int):
        if idx < 0 or idx >= len(self._images):
            return
        self._current_idx = idx
        # build warped overlay at low‑res (same scale as preview) for speed
        from ..core.stitcher import Stitcher
        quick = Stitcher(blend_mode="average").stitch(
            [self._images[idx]], [self._Hs_thumb[idx]], scale=0.25
        )
        if self.overlay_item:
            self.scene.removeItem(self.overlay_item)
        self.overlay_item = self.scene.addPixmap(cv2_to_qpix(quick))
        self.overlay_item.setOpacity(self._alpha)

    def set_overlay_opacity(self, alpha: float):
        self._alpha = alpha
        if self.overlay_item:
            self.overlay_item.setOpacity(alpha)

    # ------------------ interaction events --------------------------- #
    def keyPressEvent(self, event: QKeyEvent):
        if self._current_idx is None:
            super().keyPressEvent(event)
            return
        key = event.key()
        # 1‑px move (can hold shift for ×10)
        step = 10 if (event.modifiers() & Qt.ShiftModifier) else 1
        if key in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            dx = -step if key == Qt.Key_Left else step if key == Qt.Key_Right else 0
            dy = -step if key == Qt.Key_Up else step if key == Qt.Key_Down else 0
            self._apply_delta(translation=(dx, dy))
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        if self._current_idx is None:
            super().wheelEvent(event); return
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.ShiftModifier:  # rotation
            angle = 1 if delta > 0 else -1
            self._apply_delta(rotation=angle)
        elif event.modifiers() & Qt.AltModifier:  # scale
            factor = 1.02 if delta > 0 else 0.98
            self._apply_delta(scale=factor)
        elif event.modifiers() & Qt.ControlModifier:  # zoom view
            super().wheelEvent(event)
        else:
            super().wheelEvent(event)

    # -------------------- delta homography --------------------------- #
    def _apply_delta(self, *, translation=(0,0), rotation=0.0, scale=1.0):
        idx = self._current_idx
        tx, ty = translation
        if tx or ty:
            T = np.array([[1,0,tx],[0,1,ty],[0,0,1]], float)
        else:
            T = np.eye(3)
        if rotation:
            a = radians(rotation)
            R = np.array([[cos(a), -sin(a), 0],[sin(a), cos(a), 0],[0,0,1]], float)
        else:
            R = np.eye(3)
        if not np.isclose(scale,1.0):
            S = np.array([[scale,0,0],[0,scale,0],[0,0,1]], float)
        else:
            S = np.eye(3)
        self._deltas[idx] = T @ R @ S @ self._deltas[idx]
        # move the overlay item visually
        if self.overlay_item:
            m = self._deltas[idx]
            qtf = QTransform(m[0,0], m[1,0], m[0,1], m[1,1], m[0,2], m[1,2])
            self.overlay_item.setTransform(qtf)

    # ------------------------------------------------------------------ #
    def final_homographies(self) -> List[np.ndarray]:
        """Return H_final = delta × H_thumb for export."""
        return [d @ h for d, h in zip(self._deltas, self._Hs_thumb)]