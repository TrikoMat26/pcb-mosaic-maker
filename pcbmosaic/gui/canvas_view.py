from __future__ import annotations
from typing import List
import numpy as np, cv2
from math import cos, sin, radians

from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtGui import QPixmap, QImage, QWheelEvent, QPainter, QTransform, QKeyEvent, QPen, QBrush, QColor
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem

# ---- helper ----
def cv2_to_qpix(img: np.ndarray) -> QPixmap:
    h, w = img.shape[:2]
    rgb  = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    rgb  = np.ascontiguousarray(rgb)                  # s’assure d’un buffer compact
    bytes_per_line = 3 * w                            # *** nouvelle ligne ***
    qimg = QImage(rgb.data, w, h, bytes_per_line, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg).copy()

def pixmap_to_cv2(pixmap: QPixmap) -> np.ndarray:
    """Convertit un QPixmap en image OpenCV (BGR)."""
    qimg = pixmap.toImage()
    qimg = qimg.convertToFormat(QImage.Format_RGBA8888)
    width = qimg.width()
    height = qimg.height()
    
    # Calculer le nombre d'octets requis
    bytes_per_line = qimg.bytesPerLine()
    buffer = qimg.constBits()
    
    # Créer le tableau numpy sans setsize
    arr = np.array(buffer).reshape(height, width, 4)
    
    # Convertir RGBA en BGR
    bgr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
    return bgr



class CanvasView(QGraphicsView):
    """Preview + overlay for manual fine‑tuning."""

    # Définir le signal comme variable de classe (pas dans __init__)
    crop_changed = Signal(QRectF)

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
        self._dragging = False

        # manual‑align state
        self._images: list[np.ndarray] = []
        self._Hs_thumb: list[np.ndarray] = []
        self._deltas: list[np.ndarray] = []  # 3×3 homography delta per img
        self._current_idx: int | None = None
        self._alpha = 0.5

        # Ajouter après les autres initialisations
        self._crop_mode = False
        self._crop_rect = None
        self._crop_start = None
        self._crop_rect_item = None


    # ------------------------------------------------------------------ #
    def set_preview(self, images: List[np.ndarray], Hs: List[np.ndarray]):
        self._images = images
        self._Hs_thumb = Hs
        self._deltas = [np.eye(3) for _ in images]   # réinitialise
        self._refresh_preview()                      # ← remplace les 5 lignes d’origine
        self.setSceneRect(self.scene.itemsBoundingRect())
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)
        self._zoom = 0


    # ------------------------------------------------------------------ #
    def prepare_manual(self, images: List[np.ndarray], Hs_thumb: List[np.ndarray]):
        """Store full‑res thumbnails + initial homographies."""
        self._images = images
        self._Hs_thumb = Hs_thumb
        self._deltas = [np.eye(3) for _ in images]

    # ------------------------------------------------------------------ #
    def _refresh_preview(self):
        """Reconstruit l’aperçu basse résolution en tenant compte des ΔH."""
        from ..core.stitcher import Stitcher
        H_corr = [d @ h for d, h in zip(self._deltas, self._Hs_thumb)]
        pv = Stitcher("average").stitch(self._images, H_corr, scale=0.25)

        if self.preview_item is None:
            self.preview_item = self.scene.addPixmap(cv2_to_qpix(pv))
        else:
            self.preview_item.setPixmap(cv2_to_qpix(pv))    

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
        self.overlay_item.setTransformOriginPoint(self.overlay_item.boundingRect().center())
        # remet la dernière ΔH si elle existe
        m = self._deltas[idx]
        self.overlay_item.setTransform(QTransform(m[0,0], m[1,0],
                                                  m[0,1], m[1,1],
                                                  m[0,2], m[1,2]))

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
            return super().wheelEvent(event)

        delta = event.angleDelta().y()

        if event.modifiers() & Qt.ShiftModifier:           # rotation fine
            raw = event.angleDelta()
            steps = (raw.y() or raw.x()) / 120            # gère les pilotes qui n'envoient que X ou Y
            if steps == 0:
                return                                    # aucun mouvement
            self._apply_delta(rotation=2 * steps)         # ±2° par cran
            return                                        # pas de _finalize_move() ici
   # met à jour l’aperçu
        elif event.modifiers() & Qt.AltModifier:          # scale (zoom local)
            raw = event.angleDelta()
            steps = (raw.y() or raw.x()) / 120            # Nb de crans (+ / −)
            if steps == 0:
                return

            # tient compte du défilement “naturel”
            if event.inverted():
                steps = -steps

            factor_per_step = 1.08                        # +8 % / −8 % par cran
            s = factor_per_step ** steps                  # agrandit ou réduit
            self._apply_delta(scale=s)

            # limites raisonnables (0.2× ↔ 6×)
            cur_scale = abs(self._deltas[self._current_idx][0, 0])
            if cur_scale < 0.20:
                self._deltas[self._current_idx] *= 0.20 / cur_scale
            elif cur_scale > 6.0:
                self._deltas[self._current_idx] *= 6.0 / cur_scale

        else:
            super().wheelEvent(event)

    # ---------- gestion du drag souris ----------
    def mousePressEvent(self, e):
        if self._crop_mode and e.button() == Qt.LeftButton:
            # Démarrer un nouveau rectangle de recadrage
            self._crop_start = self.mapToScene(e.pos())
            if self._crop_rect_item:
                self.scene.removeItem(self._crop_rect_item)
            
            # Créer un nouveau rectangle vide
            self._crop_rect = QRectF(self._crop_start, self._crop_start)
            self._crop_rect_item = self.scene.addRect(
                self._crop_rect,
                QPen(QColor(255, 0, 0, 255), 2),
                QBrush(QColor(255, 0, 0, 50))
            )
            e.accept()
        elif self.overlay_item and e.button() == Qt.LeftButton:
            # Code existant pour le dragging...
            self._dragging = True
            self._drag_start = e.pos()
            self.setCursor(Qt.ClosedHandCursor)
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._crop_mode and e.buttons() & Qt.LeftButton and self._crop_start:
            # Mettre à jour le rectangle de recadrage
            current = self.mapToScene(e.pos())
            self._crop_rect = QRectF(self._crop_start, current).normalized()
            
            if self._crop_rect_item:
                self._crop_rect_item.setRect(self._crop_rect)
            e.accept()
        elif self._dragging and self.overlay_item:
            # Code existant...
            delta = self.mapToScene(e.pos()) - self.mapToScene(self._drag_start)
            self._apply_delta(translation=(delta.x(), delta.y()))
            self._drag_start = e.pos()
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._crop_mode and e.button() == Qt.LeftButton:
            # Finaliser le rectangle de recadrage
            if self._crop_rect and self._crop_rect.isValid():
                # Émettre le signal avec le rectangle final
                self.crop_changed.emit(self._crop_rect)
            e.accept()
        elif self._dragging and e.button() == Qt.LeftButton:
            # Code existant...
            self._dragging = False
            self.unsetCursor()
            self._finalize_move()
            e.accept()
        else:
            super().mouseReleaseEvent(e)


    # ------------------------------------------------------------------ #
    def _finalize_move(self):
        """Après un déplacement : met à jour le fond et cache l’overlay."""
        self._refresh_preview()            # fond à jour
        if self.overlay_item:
            self.overlay_item.setOpacity(0)  # cache complètement le doublon


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
        # clamp : évite de devenir microscopique ou gigantesque
        current_scale = self._deltas[idx][0, 0]
        if current_scale < 0.2:
            self._deltas[idx] *= 0.2 / current_scale
        elif current_scale > 5.0:
            self._deltas[idx] *= 5.0 / current_scale

        # move the overlay item visually
        if self.overlay_item:
            m = self._deltas[idx]
            qtf = QTransform(m[0,0], m[1,0], m[0,1], m[1,1], m[0,2], m[1,2])
            self.overlay_item.setTransform(qtf)
            # met à jour la pré-visualisation générale
            self._refresh_preview()


    # ------------------------------------------------------------------ #
    def final_homographies(self) -> List[np.ndarray]:
        """Renvoie uniquement les ΔH (corrections manuelles) pour chaque image."""
        return self._deltas

    def set_crop_mode(self, enabled: bool):
        """Active ou désactive le mode de recadrage interactif."""
        self._crop_mode = enabled
        
        # Supprimer le rectangle de recadrage existant si on désactive le mode
        if not enabled and self._crop_rect_item:
            self.scene.removeItem(self._crop_rect_item)
            self._crop_rect_item = None
            self._crop_rect = None
        
        # Changer le curseur
        if enabled:
            self.setCursor(Qt.CrossCursor)
        else:
            self.unsetCursor()

    def get_crop_rect(self) -> QRectF:
        """Renvoie le rectangle de recadrage actuel ou None."""
        return self._crop_rect if self._crop_rect and self._crop_rect.isValid() else None
