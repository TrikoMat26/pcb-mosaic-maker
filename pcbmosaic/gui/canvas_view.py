"""
CanvasView — vue centrale.

Modes d'affichage cohabitant :

- *manual*    (par défaut après chargement) : chaque photo est un objet
              déplaçable (PhotoItem) qu'on attrape à la souris, qu'on
              fait pivoter (Shift + molette) et redimensionner
              (Alt + molette). Le sceneRect s'étend automatiquement, la
              vue se panote à la souris (Espace + glisser ou bouton
              milieu) et zoome à la molette nue.
- *compare*   après une comparaison : la mosaïque référence est affichée
              avec les défauts surlignés ; un clic sur un défaut dans
              la liste latérale cadre dessus.

Conversion entre coordonnées vignettes et coordonnées scène :

    Chaque photo est placée dans la scène avec un *transform* initial
    qui correspond à son homographie auto-alignée H_thumb. L'utilisateur
    travaille ensuite directement dessus à la souris ; la composition
    QGraphicsItem (`sceneTransform()`) donne à tout instant l'homographie
    courante en pixels vignettes — c'est ce que `current_homographies()`
    renvoie pour l'export pleine résolution.
"""
from __future__ import annotations

from typing import List, Optional

import cv2
import numpy as np
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsView,
)


# --------------------------------------------------------------------------- #
def cv2_to_qpix(img: np.ndarray) -> QPixmap:
    h, w = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    rgb = np.ascontiguousarray(rgb)
    qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg).copy()


# --------------------------------------------------------------------------- #
class PhotoItem(QGraphicsPixmapItem):
    """
    Une photo individuelle, librement déplaçable / pivotable / scalable.

    L'utilisateur peut :
      - cliquer-glisser pour translater ;
      - Shift + molette pour pivoter autour du centre ;
      - Alt + molette pour redimensionner autour du centre ;
      - les flèches du clavier (1 px / 10 px avec Shift) pour le sub-pixel.
    """

    def __init__(self, pixmap: QPixmap, idx: int, H_initial: np.ndarray, total: int = 0):
        super().__init__(pixmap)
        self.idx = idx
        self._total = max(total, idx + 1)

        # Sélection / déplacement
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsScenePositionChanges, True)
        self.setAcceptHoverEvents(True)
        self.setTransformationMode(Qt.SmoothTransformation)

        # Centre de rotation/échelle = centre de la photo
        self.setTransformOriginPoint(pixmap.width() / 2.0, pixmap.height() / 2.0)

        # Transform de base = homographie auto-alignée
        self._H_initial = np.asarray(H_initial, dtype=np.float64).copy()
        self.setTransform(self._np_to_qtransform(self._H_initial))

        # Deltas utilisateur cumulés (en plus du transform de base)
        self._user_rot_deg = 0.0
        self._user_scale = 1.0

        # Z-order = ordre des couches.
        # Convention : haut de la liste (idx=0) = couche la plus en avant
        # (visible au-dessus des autres dans les zones de recouvrement).
        # On utilise (total - 1 - idx) pour que idx=0 ait le Z le plus haut.
        self._base_z = (self._total - 1 - idx) * 0.001
        self.setZValue(self._base_z)

        # Apparence selon l'état
        self._dragging = False

    # --- conversions matricielles -------------------------------------- #
    @staticmethod
    def _np_to_qtransform(H: np.ndarray) -> QTransform:
        # QTransform(m11, m12, m13, m21, m22, m23, m31, m32, m33)
        # avec x' = m11*x + m21*y + m31 ; y' = m12*x + m22*y + m32
        return QTransform(
            float(H[0, 0]), float(H[1, 0]), float(H[2, 0]),
            float(H[0, 1]), float(H[1, 1]), float(H[2, 1]),
            float(H[0, 2]), float(H[1, 2]), float(H[2, 2]),
        )

    @staticmethod
    def _qtransform_to_np(t: QTransform) -> np.ndarray:
        return np.array(
            [
                [t.m11(), t.m21(), t.m31()],
                [t.m12(), t.m22(), t.m32()],
                [t.m13(), t.m23(), t.m33()],
            ],
            dtype=np.float64,
        )

    # --- état utilisateur ---------------------------------------------- #
    def rotate_by(self, deg: float):
        self._user_rot_deg += deg
        self.setRotation(self._user_rot_deg)

    def scale_by(self, factor: float):
        self._user_scale *= factor
        self.setScale(self._user_scale)

    def reset_user_transform(self):
        """Annule les manipulations de l'utilisateur, garde l'auto-align."""
        self._user_rot_deg = 0.0
        self._user_scale = 1.0
        self.setRotation(0.0)
        self.setScale(1.0)
        self.setPos(0.0, 0.0)

    @property
    def user_rotation_deg(self) -> float:
        return self._user_rot_deg

    @property
    def user_scale(self) -> float:
        return self._user_scale

    @property
    def user_translation(self) -> tuple[float, float]:
        p = self.pos()
        return float(p.x()), float(p.y())

    def current_homography(self) -> np.ndarray:
        """Homographie totale (auto-align + manipulations utilisateur)."""
        return self._qtransform_to_np(self.sceneTransform())

    # --- interaction --------------------------------------------------- #
    def mousePressEvent(self, event):
        # Mise en avant lorsqu'on saisit la photo
        self.setZValue(1000.0)
        self._dragging = True
        self.setOpacity(0.7)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        self._dragging = False
        self.setOpacity(1.0)
        # Retour au Z de base après le drag (préserve l'ordre des couches
        # défini par la position dans la liste).
        self.setZValue(self._base_z)
        super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        view = self.scene().views()[0] if self.scene() and self.scene().views() else None
        if change in (
            QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged,
            QGraphicsItem.GraphicsItemChange.ItemTransformHasChanged,
            QGraphicsItem.GraphicsItemChange.ItemRotationHasChanged,
            QGraphicsItem.GraphicsItemChange.ItemScaleHasChanged,
        ):
            if view is not None:
                view.notifyItemChanged(self)
        elif change == QGraphicsItem.GraphicsItemChange.ItemSelectedHasChanged:
            if view is not None and bool(value):
                view.notifyItemSelected(self)
        return super().itemChange(change, value)

    # Sélection visuelle : un cadre autour de la photo sélectionnée
    def paint(self, painter: QPainter, option, widget=None):
        super().paint(painter, option, widget)
        if self.isSelected():
            pen = QPen(Qt.cyan, 0)  # 0 = cosmetic line (épaisseur indépendante du zoom)
            pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(self.boundingRect())


# --------------------------------------------------------------------------- #
class CanvasView(QGraphicsView):
    """Vue centrale qui héberge les PhotoItem ou l'overlay de comparaison."""

    # Signaux émis vers la fenêtre principale / le panneau
    itemSelected = Signal(int)                                      # idx
    itemTransformed = Signal(int, float, float, float, float)        # idx, tx, ty, rot, scale

    def __init__(self):
        super().__init__()
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setFocusPolicy(Qt.StrongFocus)
        self.scene = QGraphicsScene(self)
        self.setScene(self.scene)
        self.setBackgroundBrush(Qt.darkGray)

        # Manipulation des photos
        self._photo_items: List[PhotoItem] = []
        self._compare_item: Optional[QGraphicsPixmapItem] = None
        self._compare_result = None

        # Pan via Espace + clic-gauche (ou bouton du milieu)
        self._space_panning = False

    # ====================================================================
    #  API publique — cycle de vie d'un jeu de photos
    # ====================================================================
    def prepare_items(self, images: List[np.ndarray], Hs_thumb: List[np.ndarray]):
        """Crée un PhotoItem par photo, en utilisant H_thumb comme placement initial.

        L'ordre dans ``images`` détermine aussi l'ordre des couches sur le
        canvas : ``images[0]`` est dessiné au-dessus de ``images[1]``, etc.
        """
        self._reset_scene()
        self._photo_items = []
        total = len(images)
        for idx, (img, H) in enumerate(zip(images, Hs_thumb)):
            pix = cv2_to_qpix(img)
            it = PhotoItem(pix, idx, H, total=total)
            self.scene.addItem(it)
            self._photo_items.append(it)

        self._fit_scene_rect(initial=True)

    def reset_all_positions(self):
        """Remet chaque photo à sa position auto-align (sans modifs utilisateur)."""
        for it in self._photo_items:
            it.reset_user_transform()
        self._fit_scene_rect()

    def select_item(self, idx: int):
        """Sélectionne le PhotoItem d'index idx (utilisé depuis la liste latérale)."""
        if 0 <= idx < len(self._photo_items):
            for i, it in enumerate(self._photo_items):
                it.setSelected(i == idx)
            self.centerOn(self._photo_items[idx])

    def current_homographies(self) -> List[np.ndarray]:
        """Renvoie l'homographie courante de chaque photo (auto-align + manuel)."""
        return [it.current_homography() for it in self._photo_items]

    def selected_index(self) -> Optional[int]:
        """Index du PhotoItem sélectionné, ou None."""
        for it in self._photo_items:
            if it.isSelected():
                return it.idx
        return None

    def replace_photo_image(self, idx: int, new_bgr: np.ndarray):
        """
        Remplace le bitmap d'une photo (rotation, recadrage…) en gardant
        son centre à la même position dans la scène. Les manipulations
        utilisateur (translation/rotation) sont conservées.
        """
        if not (0 <= idx < len(self._photo_items)):
            return
        item = self._photo_items[idx]
        old_center = item.sceneBoundingRect().center()
        new_pix = cv2_to_qpix(new_bgr)
        item.setPixmap(new_pix)
        item.setTransformOriginPoint(new_pix.width() / 2.0, new_pix.height() / 2.0)
        # Recentre l'item pour que son centre reste où il était
        new_center = item.sceneBoundingRect().center()
        delta = old_center - new_center
        item.moveBy(delta.x(), delta.y())
        self._fit_scene_rect()

    # ====================================================================
    #  API publique — mode comparaison
    # ====================================================================
    def set_compare_overlay(self, overlay_bgr: np.ndarray, result):
        self._reset_scene()
        self._compare_item = self.scene.addPixmap(cv2_to_qpix(overlay_bgr))
        self._compare_result = result
        self.setSceneRect(self.scene.itemsBoundingRect())
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def focus_defect(self, defect_id: int):
        if not self._compare_result or self._compare_item is None:
            return
        for d in self._compare_result.defects:
            if d.id == defect_id:
                x, y, w, h = d.bbox
                margin = max(40, max(w, h) // 2)
                rect = QRectF(x - margin, y - margin, w + 2 * margin, h + 2 * margin)
                self.fitInView(rect, Qt.KeepAspectRatio)
                return

    # ====================================================================
    #  Notifications depuis les PhotoItem
    # ====================================================================
    def notifyItemChanged(self, item: PhotoItem):
        self._fit_scene_rect()
        tx, ty = item.user_translation
        self.itemTransformed.emit(
            item.idx, tx, ty, item.user_rotation_deg, item.user_scale
        )

    def notifyItemSelected(self, item: PhotoItem):
        self.itemSelected.emit(item.idx)

    # ====================================================================
    #  Interaction
    # ====================================================================
    def wheelEvent(self, event: QWheelEvent):
        # Sur Windows, Alt+molette transforme le delta Y en delta X.
        # Sur certains pilotes, Shift en fait autant. On lit donc les deux
        # axes et on prend celui qui est non nul.
        ad = event.angleDelta()
        delta = ad.y() if ad.y() != 0 else ad.x()

        # En mode comparaison : zoom de la vue
        if self._compare_item is not None:
            factor = 1.15 if delta > 0 else 1 / 1.15
            self.scale(factor, factor)
            event.accept()
            return

        # En mode manuel
        item = self._selected_or_under_mouse(event)
        mods = event.modifiers()

        if item is not None and (mods & Qt.ShiftModifier):
            # Rotation 1° par cran (10° si Ctrl en plus)
            step = 10.0 if (mods & Qt.ControlModifier) else 1.0
            item.rotate_by(step if delta > 0 else -step)
            event.accept()
            return

        if item is not None and (mods & Qt.AltModifier):
            f = 1.02 if delta > 0 else 1 / 1.02
            if mods & Qt.ControlModifier:
                f = f ** 5  # plus rapide
            item.scale_by(f)
            event.accept()
            return

        # Pas de modificateur → zoom de la vue
        factor = 1.15 if delta > 0 else 1 / 1.15
        self.scale(factor, factor)
        event.accept()

    def keyPressEvent(self, event: QKeyEvent):
        # Espace = mode pan temporaire
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_panning = True
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self._set_items_movable(False)
            event.accept()
            return

        # Flèches = nudge sub-pixel sur l'item sélectionné
        items = [it for it in self._photo_items if it.isSelected()]
        if items and event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 10 if event.modifiers() & Qt.ShiftModifier else 1
            dx = -step if event.key() == Qt.Key_Left else step if event.key() == Qt.Key_Right else 0
            dy = -step if event.key() == Qt.Key_Up else step if event.key() == Qt.Key_Down else 0
            for it in items:
                it.moveBy(dx, dy)
            event.accept()
            return

        # R = réinitialise l'item sélectionné
        if event.key() == Qt.Key_R and items:
            for it in items:
                it.reset_user_transform()
            event.accept()
            return

        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_panning = False
            self.setDragMode(QGraphicsView.NoDrag)
            self._set_items_movable(True)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        # Bouton du milieu = pan instantané
        if event.button() == Qt.MiddleButton:
            self._space_panning = True
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            self._set_items_movable(False)
            # Simuler un clic gauche pour que ScrollHandDrag prenne la main
            fake = QMouseEvent(
                QEvent.MouseButtonPress, event.position(), Qt.LeftButton,
                Qt.LeftButton, event.modifiers()
            )
            super().mousePressEvent(fake)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MiddleButton and self._space_panning:
            fake = QMouseEvent(
                QEvent.MouseButtonRelease, event.position(), Qt.LeftButton,
                Qt.LeftButton, event.modifiers()
            )
            super().mouseReleaseEvent(fake)
            self._space_panning = False
            self.setDragMode(QGraphicsView.NoDrag)
            self._set_items_movable(True)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # ====================================================================
    #  Helpers
    # ====================================================================
    def _reset_scene(self):
        self.scene.clear()
        self._photo_items = []
        self._compare_item = None
        self._compare_result = None

    def _set_items_movable(self, on: bool):
        for it in self._photo_items:
            it.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, on)

    def _selected_or_under_mouse(self, event: QWheelEvent) -> Optional[PhotoItem]:
        """Cherche l'item sélectionné ; à défaut, l'item sous le curseur."""
        for it in self._photo_items:
            if it.isSelected():
                return it
        scene_pos = self.mapToScene(event.position().toPoint())
        for it in reversed(self._photo_items):  # haut d'abord
            if it.contains(it.mapFromScene(scene_pos)):
                return it
        return None

    def _fit_scene_rect(self, initial: bool = False):
        """Recalcule sceneRect pour englober toutes les photos + marge."""
        if not self._photo_items:
            return
        rect = QRectF()
        for it in self._photo_items:
            r = it.sceneBoundingRect()
            rect = r if rect.isNull() else rect.united(r)
        margin = max(rect.width(), rect.height()) * 0.5  # 50 % d'air
        rect.adjust(-margin, -margin, margin, margin)
        self.setSceneRect(rect)
        if initial:
            # Cadre initial : on englobe juste les photos sans la marge
            tight = QRectF()
            for it in self._photo_items:
                r = it.sceneBoundingRect()
                tight = r if tight.isNull() else tight.united(r)
            self.fitInView(tight, Qt.KeepAspectRatio)
