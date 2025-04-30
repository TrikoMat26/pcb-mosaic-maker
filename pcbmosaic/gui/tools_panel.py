from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QSlider,
    QComboBox,
    QGroupBox,
    QSizePolicy,
)

class ToolsPanel(QWidget):
    def __init__(self):
        super().__init__()
        self._canvas = None
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Expanding)
        self._build_ui()

    # ------------------------------------------------------------------ #
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)

        # Résolution
        gb_out = QGroupBox("Résolution sortie")
        out_lay = QVBoxLayout(gb_out)
        self.cmb_scale = QComboBox()
        self.cmb_scale.addItems(["x1", "x1.5", "x2", "Custom…"])
        out_lay.addWidget(self.cmb_scale)
        lay.addWidget(gb_out)

        lay.addStretch(1)

    # ------------------------------------------------------------------ #
    def set_images(self, canvas):
        self._canvas = canvas

    # ------------------------------------------------------------------ #
    def output_scale(self) -> float:
        txt = self.cmb_scale.currentText()
        if txt == "x1":
            return 1.0
        if txt == "x1.5":
            return 1.5
        if txt == "x2":
            return 2.0
        # Custom — à implémenter
        return 1.0
