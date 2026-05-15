"""
ToolsPanel — panneau latéral droit.

Sections :

1. Résolution de sortie
2. Mode d'alignement (phase / sift / orb)
3. Photos chargées (clic = sélection sur le canevas)
4. Manipulation manuelle (lecture des tx/ty/rot/scale + bouton Reset)
5. Comparaison (liste cliquable des défauts)
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# --------------------------------------------------------------------------- #
class ToolsPanel(QWidget):
    """Panneau de droite."""

    alignerModeChanged = Signal(str)
    photoSelected = Signal(int)
    resetPositionsRequested = Signal()
    defectSelected = Signal(int)
    # Emis quand l'utilisateur réordonne les photos.
    # Charge utile : liste des chemins dans leur nouvel ordre.
    photoOrderChanged = Signal(list)

    def __init__(self):
        super().__init__()
        self._canvas = None
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Expanding)
        self.setMinimumWidth(300)
        self._build_ui()

    # ------------------------------------------------------------------ #
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(8)

        # ----- 1. Résolution ----- #
        gb_out = QGroupBox("Résolution de sortie")
        out_lay = QVBoxLayout(gb_out)
        self.cmb_scale = QComboBox()
        self.cmb_scale.addItems(["x1", "x1.5", "x2"])
        out_lay.addWidget(self.cmb_scale)
        lay.addWidget(gb_out)

        # ----- 2. Mode d'alignement ----- #
        gb_alg = QGroupBox("Mode d'alignement")
        alg_lay = QVBoxLayout(gb_alg)
        self.cmb_aligner = QComboBox()
        self.cmb_aligner.addItems(["phase", "sift", "orb"])
        self.cmb_aligner.currentTextChanged.connect(self.alignerModeChanged.emit)
        alg_lay.addWidget(self.cmb_aligner)
        alg_lay.addWidget(QLabel(
            "<small><i>« phase » : recommandé pour PCB pris depuis<br>"
            "la même incidence (sub-pixel, robuste).</i></small>"
        ))
        lay.addWidget(gb_alg)

        # ----- 3. Liste des photos / ordre des couches ----- #
        gb_imgs = QGroupBox("Photos chargées — ordre des couches")
        i_lay = QVBoxLayout(gb_imgs)
        self.lst_images = QListWidget()
        self.lst_images.currentRowChanged.connect(self._on_select_image)
        # Réorganisation interne par glisser-déposer
        self.lst_images.setDragDropMode(QAbstractItemView.InternalMove)
        self.lst_images.setDefaultDropAction(Qt.MoveAction)
        self.lst_images.setSelectionMode(QAbstractItemView.SingleSelection)
        # Le `rowsMoved` du modèle se déclenche après chaque drop interne
        self.lst_images.model().rowsMoved.connect(self._on_rows_moved)
        i_lay.addWidget(self.lst_images, stretch=1)

        # Boutons « avancer / reculer la couche » (alternative au drag-drop)
        order_btns = QHBoxLayout()
        self.btn_up = QPushButton("▲ Avancer")
        self.btn_down = QPushButton("▼ Reculer")
        self.btn_up.setToolTip("Met la photo sélectionnée au-dessus de la précédente")
        self.btn_down.setToolTip("Met la photo sélectionnée en dessous de la suivante")
        self.btn_up.clicked.connect(self._move_selected_up)
        self.btn_down.clicked.connect(self._move_selected_down)
        order_btns.addWidget(self.btn_up)
        order_btns.addWidget(self.btn_down)
        i_lay.addLayout(order_btns)

        i_lay.addWidget(QLabel(
            "<small><i>Le <b>haut de la liste</b> = couche au-dessus dans les "
            "zones de recouvrement (canvas et mosaïque exportée). "
            "Glisser-déposer ou ▲▼ pour changer l'ordre.<br>"
            "Cliquer un nom = sélectionne la photo sur le canevas.</i></small>"
        ))
        lay.addWidget(gb_imgs, stretch=1)

        # ----- 4. Manipulation manuelle ----- #
        gb_man = QGroupBox("Manipulation directe")
        m_lay = QVBoxLayout(gb_man)
        self.lbl_transform = QLabel("<i>Aucune photo sélectionnée.</i>")
        self.lbl_transform.setTextFormat(Qt.RichText)
        m_lay.addWidget(self.lbl_transform)

        self.btn_reset = QPushButton("Réinitialiser les positions")
        self.btn_reset.clicked.connect(self.resetPositionsRequested.emit)
        m_lay.addWidget(self.btn_reset)

        m_lay.addWidget(QLabel(
            "<small><b>Souris :</b><br>"
            "&bull; <b>Clic-glisser</b> : déplacer une photo<br>"
            "&bull; <b>Bouton du milieu</b> ou <b>Espace+glisser</b> : panoramique<br>"
            "&bull; <b>Molette</b> : zoom de la vue<br>"
            "&bull; <b>Shift+molette</b> : rotation (Ctrl pour ×10)<br>"
            "&bull; <b>Alt+molette</b> : échelle (Ctrl pour rapide)<br>"
            "<b>Clavier (photo sélectionnée) :</b><br>"
            "&bull; Flèches = 1 px (Shift = 10 px)<br>"
            "&bull; <b>R</b> = réinitialise la photo</small>"
        ))
        lay.addWidget(gb_man)

        # ----- 5. Comparaison ----- #
        gb_cmp = QGroupBox("Défauts détectés")
        c_lay = QVBoxLayout(gb_cmp)
        self.lbl_defects = QLabel("<i>Aucune comparaison effectuée.</i>")
        c_lay.addWidget(self.lbl_defects)
        self.lst_defects = QListWidget()
        self.lst_defects.itemClicked.connect(self._on_defect_clicked)
        c_lay.addWidget(self.lst_defects, stretch=1)
        c_lay.addWidget(QLabel(
            "<small>Cliquer un défaut pour cadrer la vue dessus.</small>"
        ))
        lay.addWidget(gb_cmp, stretch=2)

    # ------------------------------------------------------------------ #
    #  API publique
    # ------------------------------------------------------------------ #
    def set_canvas(self, canvas, file_names: List[str]):
        # Évite la double-connexion si on rappelle set_canvas après un re-load.
        if self._canvas is not canvas:
            try:
                if self._canvas is not None:
                    self._canvas.itemSelected.disconnect(self._sync_selection_from_canvas)
                    self._canvas.itemTransformed.disconnect(self._update_transform_label)
            except (RuntimeError, TypeError):
                pass
            self._canvas = canvas
            canvas.itemSelected.connect(self._sync_selection_from_canvas)
            canvas.itemTransformed.connect(self._update_transform_label)

        # Bloque le signal rowsMoved pendant qu'on repeuple la liste
        # (sinon clear() + addItem() en série déclencherait notre slot).
        self.lst_images.model().blockSignals(True)
        self.lst_images.blockSignals(True)
        self.lst_images.clear()
        for fn in file_names:
            item = QListWidgetItem(Path(fn).name)
            # On stocke le chemin complet comme identifiant stable utilisé
            # pour calculer la permutation lors d'un réordonnement.
            item.setData(Qt.UserRole, str(fn))
            self.lst_images.addItem(item)
        if self.lst_images.count():
            self.lst_images.setCurrentRow(len(file_names) // 2)
        self.lst_images.blockSignals(False)
        self.lst_images.model().blockSignals(False)

    def set_defects(self, defects):
        self.lst_defects.clear()
        if not defects:
            self.lbl_defects.setText("<b>Aucun défaut détecté.</b>")
            return
        self.lbl_defects.setText(
            f"<b>{len(defects)} défauts détectés</b> (triés par sévérité)."
        )
        for d in defects:
            txt = f"#{d.id:>2}  sev={d.severity:.2f}  ({d.area_px}px)"
            it = QListWidgetItem(txt)
            it.setData(Qt.UserRole, d.id)
            hue = int((1.0 - d.severity) * 0.33 * 360)
            color = QColor.fromHsv(hue, 180, 230)
            it.setBackground(color)
            self.lst_defects.addItem(it)

    def output_scale(self) -> float:
        return {"x1": 1.0, "x1.5": 1.5, "x2": 2.0}.get(
            self.cmb_scale.currentText(), 1.0
        )

    # ------------------------------------------------------------------ #
    #  Slots internes
    # ------------------------------------------------------------------ #
    def _on_select_image(self, row: int):
        if row >= 0:
            self.photoSelected.emit(row)
            if self._canvas:
                self._canvas.select_item(row)

    def _sync_selection_from_canvas(self, idx: int):
        # Réagir à un clic direct sur le canevas
        self.lst_images.blockSignals(True)
        self.lst_images.setCurrentRow(idx)
        self.lst_images.blockSignals(False)

    def _update_transform_label(
        self, idx: int, tx: float, ty: float, rot: float, scale: float
    ):
        self.lbl_transform.setText(
            f"<b>Photo #{idx + 1}</b><br>"
            f"&bull; tx = <code>{tx:+.1f}</code> px&nbsp;&nbsp;"
            f"ty = <code>{ty:+.1f}</code> px<br>"
            f"&bull; rotation = <code>{rot:+.2f}°</code><br>"
            f"&bull; échelle = <code>×{scale:.3f}</code>"
        )

    def _on_defect_clicked(self, item: QListWidgetItem):
        defect_id = item.data(Qt.UserRole)
        if defect_id is not None:
            self.defectSelected.emit(int(defect_id))

    # ------------------------------------------------------------------ #
    #  Réordonnancement
    # ------------------------------------------------------------------ #
    def _current_paths_order(self) -> List[str]:
        return [
            self.lst_images.item(i).data(Qt.UserRole)
            for i in range(self.lst_images.count())
        ]

    def _emit_order(self):
        """Diffuse l'ordre courant ; MainWindow met à jour ses données."""
        order = self._current_paths_order()
        # None éventuels = items sans UserRole = on ignore (cas pathologique)
        if any(p is None for p in order):
            return
        self.photoOrderChanged.emit(order)

    def _on_rows_moved(self, *args, **kwargs):
        # Déclenché après un drop interne du QListWidget
        self._emit_order()

    def _swap_rows(self, row_a: int, row_b: int):
        if row_a == row_b:
            return
        # On évite que le signal currentRowChanged ne fasse sauter le canvas
        # pendant l'opération.
        self.lst_images.blockSignals(True)
        item_a = self.lst_images.takeItem(row_a)
        # Après takeItem, row_b ne bouge pas si row_a > row_b ; sinon il
        # décale de -1.
        adj_b = row_b - 1 if row_a < row_b else row_b
        item_b = self.lst_images.takeItem(adj_b)
        # Réinsère dans l'ordre inversé pour respecter les nouvelles positions
        if row_a < row_b:
            self.lst_images.insertItem(row_a, item_b)
            self.lst_images.insertItem(row_b, item_a)
        else:
            self.lst_images.insertItem(row_b, item_a)
            self.lst_images.insertItem(row_a, item_b)
        self.lst_images.setCurrentRow(row_b)
        self.lst_images.blockSignals(False)
        self._emit_order()

    def _move_selected_up(self):
        row = self.lst_images.currentRow()
        if row > 0:
            self._swap_rows(row, row - 1)

    def _move_selected_down(self):
        row = self.lst_images.currentRow()
        if 0 <= row < self.lst_images.count() - 1:
            self._swap_rows(row, row + 1)
