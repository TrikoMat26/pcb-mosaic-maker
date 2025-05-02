from __future__ import annotations
from typing import Optional
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QSlider, QComboBox, QGroupBox,
    QSizePolicy, QListWidget, QListWidgetItem, QHBoxLayout
)

class ToolsPanel(QWidget):
    """Right‑side panel: output resolution *and* manual alignment widgets."""

    def __init__(self):
        super().__init__()
        self._canvas = None
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Expanding)
        self._build_ui()

    # ------------------------------------------------------------------ #
    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)

        # ----- output resolution -----
        gb_out = QGroupBox("Résolution sortie")
        out_lay = QVBoxLayout(gb_out)
        self.cmb_scale = QComboBox()
        self.cmb_scale.addItems(["x1", "x1.5", "x2", "Custom…"])
        out_lay.addWidget(self.cmb_scale)
        lay.addWidget(gb_out)

        # ----- manual alignment -----
        gb_align = QGroupBox("Alignement manuel (A/B switch)")
        a_lay = QVBoxLayout(gb_align)
        self.lst_images = QListWidget()
        self.lst_images.currentRowChanged.connect(self._on_select)
        self.sld_alpha = QSlider(Qt.Horizontal)
        self.sld_alpha.setRange(0, 100)
        self.sld_alpha.setValue(50)
        self.sld_alpha.valueChanged.connect(self._on_alpha)
        a_lay.addWidget(self.lst_images)
        cap = QLabel("Opacité superposition")
        a_lay.addWidget(cap)
        a_lay.addWidget(self.sld_alpha)
        lay.addWidget(gb_align)

        lay.addStretch(1)

    # ------------------------------------------------------------------ #
    def set_canvas(self, canvas, file_names: list[str]):
        """Bind the canvas + populate image list."""
        self._canvas = canvas
        self.lst_images.clear()
        for fn in file_names:
            item = QListWidgetItem(Path(fn).name)
            self.lst_images.addItem(item)
        if self.lst_images.count():
            self.lst_images.setCurrentRow(len(file_names)//2)

    # ------------------------------------------------------------------ #
    def _on_select(self, row: int):
        if self._canvas:
            self._canvas.select_overlay(row)

    def _on_alpha(self, val: int):
        if self._canvas:
            self._canvas.set_overlay_opacity(val/100.0)

    # ------------------------------------------------------------------ #
    def output_scale(self) -> float:
        txt = self.cmb_scale.currentText()
        return {"x1": 1.0, "x1.5": 1.5, "x2": 2.0}.get(txt, 1.0)