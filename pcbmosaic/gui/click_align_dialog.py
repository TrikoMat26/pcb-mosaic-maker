"""
ClickAlignDialog — alignement assisté par clics.

Pour chaque paire de photos consécutives (i, i+1), l'utilisateur clique
sur N points correspondants (N >= 2). On calcule par moindres carrés une
similarité (translation + rotation + échelle uniforme), puis on chaîne
toutes les paires vers la photo de référence centrale.

UX :

- Deux vues côte à côte : GAUCHE = image i, DROITE = image i+1.
- L'utilisateur clique alternativement GAUCHE puis DROITE pour ajouter
  une paire de points. Un marqueur numéroté coloré apparaît sur les deux
  vues à chaque paire complétée.
- Boutons : Annuler dernier point · Recommencer cette paire ·
  Paire précédente · Paire suivante · Terminer.
- Molette = zoom centré sur le curseur, bouton du milieu = panoramique.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import cv2
import numpy as np
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QGraphicsEllipseItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


# --------------------------------------------------------------------------- #
def _cv2_to_qpix(img: np.ndarray) -> QPixmap:
    h, w = img.shape[:2]
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    rgb = np.ascontiguousarray(rgb)
    qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888)
    return QPixmap.fromImage(qimg).copy()


def _color_for_index(i: int) -> QColor:
    """Palette de couleurs distinctes pour les marqueurs numérotés."""
    h = (i * 47) % 360                  # teintes bien réparties
    return QColor.fromHsv(h, 220, 240)


# --------------------------------------------------------------------------- #
class _ClickableView(QGraphicsView):
    """Vue qui transmet les clics gauche dans le repère de la scène."""

    leftClicked = Signal(QPointF)

    def __init__(self):
        super().__init__()
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(Qt.black)
        self.setMouseTracking(True)
        self._marker_items = []
        self._image_item = None
        self._panning = False

    # ------------------------------------------------------------------ #
    def set_image(self, img_bgr: np.ndarray):
        self._scene.clear()
        self._marker_items = []
        pix = _cv2_to_qpix(img_bgr)
        self._image_item = self._scene.addPixmap(pix)
        self.setSceneRect(QRectF(pix.rect()))
        self.fitInView(self.sceneRect(), Qt.KeepAspectRatio)

    def add_marker(self, pos: QPointF, label: str, color: QColor):
        r = 12
        ellipse = self._scene.addEllipse(
            pos.x() - r, pos.y() - r, 2 * r, 2 * r,
            QPen(Qt.white, 2), QBrush(color),
        )
        ellipse.setZValue(10)
        text = self._scene.addText(label)
        text.setDefaultTextColor(Qt.white)
        f = text.font()
        f.setBold(True)
        f.setPointSize(10)
        text.setFont(f)
        # Centrer le texte sur l'ellipse
        br = text.boundingRect()
        text.setPos(pos.x() - br.width() / 2, pos.y() - br.height() / 2)
        text.setZValue(11)
        self._marker_items.append((ellipse, text))

    def clear_markers(self):
        for ell, txt in self._marker_items:
            self._scene.removeItem(ell)
            self._scene.removeItem(txt)
        self._marker_items = []

    def remove_last_marker(self):
        if self._marker_items:
            ell, txt = self._marker_items.pop()
            self._scene.removeItem(ell)
            self._scene.removeItem(txt)

    # ------------------------------------------------------------------ #
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self.setDragMode(QGraphicsView.ScrollHandDrag)
            fake = QMouseEvent(
                QEvent.MouseButtonPress, event.position(), Qt.LeftButton,
                Qt.LeftButton, event.modifiers(),
            )
            super().mousePressEvent(fake)
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            scene_pos = self.mapToScene(event.position().toPoint())
            self.leftClicked.emit(scene_pos)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MiddleButton and self._panning:
            fake = QMouseEvent(
                QEvent.MouseButtonRelease, event.position(), Qt.LeftButton,
                Qt.LeftButton, event.modifiers(),
            )
            super().mouseReleaseEvent(fake)
            self._panning = False
            self.setDragMode(QGraphicsView.NoDrag)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent):
        ad = event.angleDelta()
        delta = ad.y() if ad.y() != 0 else ad.x()
        factor = 1.15 if delta > 0 else 1 / 1.15
        self.scale(factor, factor)
        event.accept()


# --------------------------------------------------------------------------- #
class ClickAlignDialog(QDialog):
    """Boîte de dialogue qui collecte des paires de points pour N-1 paires."""

    def __init__(
        self,
        images: List[np.ndarray],
        file_names: List[str],
        parent: Optional[QWidget] = None,
        initial_pair_clicks: Optional[
            List[List[Tuple[Tuple[float, float], Tuple[float, float]]]]
        ] = None,
    ):
        """
        Paramètres
        ----------
        initial_pair_clicks : liste optionnelle de clics à pré-remplir
            (même format que ``get_pair_clicks()``). Permet de rouvrir la
            boîte avec les correspondances déjà saisies lors d'une session
            précédente. Les paires manquantes (ex : nouvelles photos
            ajoutées après coup) sont initialisées vides.
        """
        super().__init__(parent)
        self._images = images
        self._names = file_names
        self._n = len(images)
        # Pour chaque paire (k, k+1) : liste de clics dans l'ordre d'arrivée.
        # Chaque clic = ('A', x, y) ou ('B', x, y).
        self._clicks: List[List[Tuple[str, float, float]]] = [
            [] for _ in range(self._n - 1)
        ]
        # Pré-remplit si un état précédent a été fourni
        if initial_pair_clicks is not None:
            for k, pairs in enumerate(initial_pair_clicks):
                if k >= len(self._clicks):
                    break
                for (ax, ay), (bx, by) in pairs:
                    self._clicks[k].append(("A", float(ax), float(ay)))
                    self._clicks[k].append(("B", float(bx), float(by)))
        self._current = 0  # index de la paire courante (0..n-2)

        self.setWindowTitle("Alignement par clics")
        self.resize(1280, 760)
        self._build_ui()
        self._show_pair(0)

    # ====================================================================
    #  UI
    # ====================================================================
    def _build_ui(self):
        lay = QVBoxLayout(self)

        # Titre + indicateur de paire
        self._lbl_title = QLabel()
        self._lbl_title.setTextFormat(Qt.RichText)
        lay.addWidget(self._lbl_title)

        # Instruction dynamique (côté à cliquer)
        self._lbl_instr = QLabel()
        self._lbl_instr.setTextFormat(Qt.RichText)
        lay.addWidget(self._lbl_instr)

        # Vues côte à côte
        h = QHBoxLayout()
        self._view_a = _ClickableView()
        self._view_b = _ClickableView()
        self._view_a.leftClicked.connect(lambda p: self._on_click("A", p))
        self._view_b.leftClicked.connect(lambda p: self._on_click("B", p))
        h.addWidget(self._view_a, stretch=1)
        h.addWidget(self._view_b, stretch=1)
        lay.addLayout(h, stretch=1)

        # Toolbar de navigation
        tools = QHBoxLayout()
        self.btn_undo = QPushButton("Annuler dernier point")
        self.btn_reset = QPushButton("Recommencer cette paire")
        self.btn_prev = QPushButton("← Paire précédente")
        self.btn_next = QPushButton("Paire suivante →")
        self.btn_undo.clicked.connect(self._undo_last_click)
        self.btn_reset.clicked.connect(self._reset_current_pair)
        self.btn_prev.clicked.connect(self._goto_prev_pair)
        self.btn_next.clicked.connect(self._goto_next_pair)
        tools.addWidget(self.btn_undo)
        tools.addWidget(self.btn_reset)
        tools.addStretch()
        tools.addWidget(self.btn_prev)
        tools.addWidget(self.btn_next)
        lay.addLayout(tools)

        # OK / Annuler
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._on_accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Ok).setText("Terminer et appliquer")
        lay.addWidget(bb)

        # Raccourcis utiles (Ctrl+Z = annuler, PgDn/PgUp = navigation)
        from PySide6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self._undo_last_click)
        QShortcut(QKeySequence("PgUp"),   self, activated=self._goto_prev_pair)
        QShortcut(QKeySequence("PgDown"), self, activated=self._goto_next_pair)

    # ====================================================================
    #  Affichage d'une paire
    # ====================================================================
    def _show_pair(self, k: int):
        self._current = k
        self._view_a.set_image(self._images[k])
        self._view_b.set_image(self._images[k + 1])
        self._redraw_markers_for_current()
        self._refresh_labels()
        self.btn_prev.setEnabled(k > 0)
        self.btn_next.setEnabled(k < self._n - 2)

    def _redraw_markers_for_current(self):
        self._view_a.clear_markers()
        self._view_b.clear_markers()
        clicks = self._clicks[self._current]
        # Compte paires complètes : chaque cycle A puis B incrémente le n°
        pair_num = 0
        i = 0
        while i < len(clicks):
            side, x, y = clicks[i]
            if side == "A":
                # Cherche un B juste après
                if i + 1 < len(clicks) and clicks[i + 1][0] == "B":
                    pair_num += 1
                    color = _color_for_index(pair_num - 1)
                    _, bx, by = clicks[i + 1]
                    self._view_a.add_marker(QPointF(x, y), str(pair_num), color)
                    self._view_b.add_marker(QPointF(bx, by), str(pair_num), color)
                    i += 2
                    continue
                else:
                    # A en attente de son B
                    pair_num += 1
                    color = _color_for_index(pair_num - 1)
                    color.setAlpha(140)
                    self._view_a.add_marker(QPointF(x, y), str(pair_num) + "?", color)
                    i += 1
                    continue
            elif side == "B":
                # B en attente de son A (rare : si l'utilisateur a cliqué dans le mauvais ordre)
                pair_num += 1
                color = _color_for_index(pair_num - 1)
                color.setAlpha(140)
                self._view_b.add_marker(QPointF(x, y), str(pair_num) + "?", color)
                i += 1

    def _refresh_labels(self):
        name_a = self._names[self._current] if self._current < len(self._names) else "?"
        name_b = (
            self._names[self._current + 1]
            if self._current + 1 < len(self._names) else "?"
        )
        self._lbl_title.setText(
            f"<h3 style='margin:0'>Paire {self._current + 1} / {self._n - 1}</h3>"
            f"<small>GAUCHE&nbsp;: <b>{name_a}</b>&nbsp;&nbsp;"
            f"DROITE&nbsp;: <b>{name_b}</b></small>"
        )
        complete = self._count_complete_pairs(self._current)
        expected = self._next_expected_side()
        side_txt = (
            "<span style='color:#3ea6ff'><b>GAUCHE</b></span>"
            if expected == "A"
            else "<span style='color:#3ea6ff'><b>DROITE</b></span>"
        )
        ok_color = "#4caf50" if complete >= 3 else "#ff9800"
        self._lbl_instr.setText(
            f"<small>"
            f"<span style='color:{ok_color}'><b>{complete}/3 paire(s)</b></span>"
            f" cliquée(s). &nbsp;Prochain clic : photo {side_txt}."
            f" &nbsp;<i>Minimum 3 paires bien espacées par couple d'images.</i>"
            f"</small>"
        )

    # ====================================================================
    #  Interaction
    # ====================================================================
    def _next_expected_side(self) -> str:
        """Renvoie 'A' ou 'B' selon ce qu'il manque."""
        clicks = self._clicks[self._current]
        # Si dernier clic est un A solitaire → on attend un B
        if clicks and clicks[-1][0] == "A":
            # Sauf s'il y avait déjà un B avant → on alterne normalement
            # Cas simple : impair = A en attente, pair = on attend A.
            # On utilise plutôt le comptage de A vs B.
            pass
        n_a = sum(1 for c in clicks if c[0] == "A")
        n_b = sum(1 for c in clicks if c[0] == "B")
        return "A" if n_a == n_b else "B"

    def _on_click(self, side: str, pos: QPointF):
        expected = self._next_expected_side()
        clicks = self._clicks[self._current]
        if side != expected:
            # Si l'utilisateur reclique sur le même côté que celui en attente
            # de complément, on remplace le clic en attente (il a changé d'avis).
            if clicks and clicks[-1][0] == side:
                clicks[-1] = (side, float(pos.x()), float(pos.y()))
            else:
                # Cas anormal — on l'accepte quand même, mais ça créera un
                # marqueur "?" lors du redraw.
                clicks.append((side, float(pos.x()), float(pos.y())))
        else:
            clicks.append((side, float(pos.x()), float(pos.y())))
        self._redraw_markers_for_current()
        self._refresh_labels()

    def _undo_last_click(self):
        clicks = self._clicks[self._current]
        if clicks:
            clicks.pop()
            self._redraw_markers_for_current()
            self._refresh_labels()

    def _reset_current_pair(self):
        self._clicks[self._current] = []
        self._redraw_markers_for_current()
        self._refresh_labels()

    def _goto_prev_pair(self):
        if self._current > 0:
            self._show_pair(self._current - 1)

    def _goto_next_pair(self):
        if self._current < self._n - 2:
            self._show_pair(self._current + 1)

    # ====================================================================
    #  Sortie
    # ====================================================================
    def _count_complete_pairs(self, k: int) -> int:
        """Nombre de paires (A, B) complètes pour la paire d'images k."""
        clicks = self._clicks[k]
        n = 0
        i = 0
        while i < len(clicks):
            if (
                clicks[i][0] == "A"
                and i + 1 < len(clicks)
                and clicks[i + 1][0] == "B"
            ):
                n += 1
                i += 2
            else:
                i += 1
        return n

    def _extract_point_pairs(self, k: int) -> List[Tuple[Tuple[float, float], Tuple[float, float]]]:
        """Sortie propre pour `Aligner.align_from_clicks` : list[(pa, pb)]."""
        out = []
        clicks = self._clicks[k]
        i = 0
        while i < len(clicks):
            if (
                clicks[i][0] == "A"
                and i + 1 < len(clicks)
                and clicks[i + 1][0] == "B"
            ):
                _, ax, ay = clicks[i]
                _, bx, by = clicks[i + 1]
                out.append(((ax, ay), (bx, by)))
                i += 2
            else:
                i += 1
        return out

    def get_pair_clicks(self) -> List[List[Tuple[Tuple[float, float], Tuple[float, float]]]]:
        """Liste, par paire d'images, des correspondances cliquées."""
        return [self._extract_point_pairs(k) for k in range(self._n - 1)]

    def _on_accept(self):
        # Validation : au moins 3 correspondances par paire qui en a au moins une.
        # (3 points = 1 de plus que le minimum théorique → tolérance aux clics
        #  imprécis et meilleure détermination de rotation + échelle.)
        MIN_PAIRS = 3
        missing = []
        no_clicks = []
        for k in range(self._n - 1):
            c = self._count_complete_pairs(k)
            if c == 0:
                no_clicks.append(k + 1)
            elif c < MIN_PAIRS:
                missing.append(k + 1)
        if missing:
            QMessageBox.warning(
                self,
                "Pas assez de points",
                f"Il faut au moins {MIN_PAIRS} paires de points par couple d'images\n"
                "(ça permet de déterminer translation, rotation ET échelle de façon\n"
                "robuste). Paires incomplètes : "
                + ", ".join(f"#{k}" for k in missing),
            )
            return
        if no_clicks:
            ret = QMessageBox.question(
                self,
                "Paires sans points",
                f"Les paires #{', #'.join(str(k) for k in no_clicks)} n'ont "
                "aucun point cliqué. Ces photos seront posées à l'identité "
                "(toutes au même endroit). Continuer quand même ?",
            )
            if ret != QMessageBox.Yes:
                return
        self.accept()
