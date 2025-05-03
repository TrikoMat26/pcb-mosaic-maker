from __future__ import annotations
from typing import Optional
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QSlider, QComboBox, QGroupBox,
    QSizePolicy, QListWidget, QListWidgetItem, QHBoxLayout,
    QPushButton, QCheckBox, QLineEdit, QMessageBox
)
from PySide6.QtCore import Qt
import numpy as np
import cv2
from ..gui.canvas_view import pixmap_to_cv2, cv2_to_qpix

class ToolsPanel(QWidget):
    """Right‑side panel: output resolution *and* manual alignment widgets."""

    def __init__(self):
        super().__init__()
        self._canvas = None
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Expanding)
        self._build_ui()
        self._custom_dimensions = None


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

        # Ajouter une section pour le recadrage
        gb_crop = QGroupBox("Recadrage avancé")
        crop_lay = QVBoxLayout(gb_crop)

        # Bouton pour activer/désactiver le mode recadrage
        self.btn_crop_mode = QPushButton("Activer recadrage interactif")
        self.btn_crop_mode.setCheckable(True)
        self.btn_crop_mode.toggled.connect(self._on_crop_mode_toggled)

        # Bouton pour réinitialiser le recadrage
        self.btn_reset_crop = QPushButton("Réinitialiser recadrage")
        self.btn_reset_crop.clicked.connect(self._on_reset_crop)

        # Bouton pour recadrage automatique
        self.btn_auto_crop = QPushButton("Recadrage automatique")
        self.btn_auto_crop.clicked.connect(self._on_auto_crop)

        # Checkbox pour activer/désactiver le recadrage automatique à l'export
        self.chk_auto_crop_export = QCheckBox("Recadrage auto à l'export")
        self.chk_auto_crop_export.setChecked(True)

        # Ajouter des contrôles pour les dimensions exactes
        dim_layout = QHBoxLayout()
        dim_layout.addWidget(QLabel("Dimensions:"))
        self.txt_width = QLineEdit()
        self.txt_width.setPlaceholderText("Largeur")
        self.txt_height = QLineEdit()
        self.txt_height.setPlaceholderText("Hauteur")
        dim_layout.addWidget(self.txt_width)
        dim_layout.addWidget(QLabel("×"))
        dim_layout.addWidget(self.txt_height)
        self.btn_apply_dims = QPushButton("Appliquer")
        self.btn_apply_dims.clicked.connect(self._on_apply_dimensions)
        dim_layout.addWidget(self.btn_apply_dims)

        # Préréglages de format
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Format:"))
        self.cmb_format = QComboBox()
        self.cmb_format.addItems(["Original", "16:9", "4:3", "1:1", "A4", "A3"])
        self.cmb_format.currentIndexChanged.connect(self._on_format_changed)
        format_layout.addWidget(self.cmb_format)

        # Ajouter tous les widgets au layout
        crop_lay.addWidget(self.btn_crop_mode)
        crop_lay.addWidget(self.btn_reset_crop)
        crop_lay.addWidget(self.btn_auto_crop)
        crop_lay.addWidget(self.chk_auto_crop_export)
        crop_lay.addLayout(dim_layout)
        crop_lay.addLayout(format_layout)

        lay.addWidget(gb_crop)
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
    
    def _on_crop_mode_toggled(self, enabled):
        if self._canvas:
            self._canvas.set_crop_mode(enabled)
            self.btn_crop_mode.setText(
                "Désactiver recadrage" if enabled else "Activer recadrage interactif"
            )

    def _on_reset_crop(self):
        if self._canvas:
            self._canvas.set_crop_mode(False)
            self.btn_crop_mode.setChecked(False)
            # Réinitialiser le rectangle de recadrage
            if hasattr(self._canvas, "_crop_rect_item") and self._canvas._crop_rect_item:
                self._canvas.scene.removeItem(self._canvas._crop_rect_item)
                self._canvas._crop_rect_item = None
                self._canvas._crop_rect = None

    def _on_auto_crop(self):
        if self._canvas and hasattr(self._canvas, "preview_item") and self._canvas.preview_item:
            # Obtenir l'image preview
            pixmap = self._canvas.preview_item.pixmap()
            img = pixmap_to_cv2(pixmap)
            
            # Utiliser Stitcher.auto_crop_mosaic
            from ..core.stitcher import Stitcher
            cropped = Stitcher().auto_crop_mosaic(img)
            
            # Mettre à jour l'aperçu
            self._canvas.preview_item.setPixmap(cv2_to_qpix(cropped))

    def _on_apply_dimensions(self):
        try:
            width = int(self.txt_width.text())
            height = int(self.txt_height.text())
            
            if width <= 0 or height <= 0:
                raise ValueError("Les dimensions doivent être positives")
            
            # Stocker pour l'export
            self._custom_dimensions = (width, height)
        except ValueError as e:
            QMessageBox.warning(self, "Erreur", str(e))

    def _on_format_changed(self, index):
        if index == 0 or not self._canvas or not hasattr(self._canvas, "preview_item"):
            return
        
        pixmap = self._canvas.preview_item.pixmap()
        current_width = pixmap.width()
        current_height = pixmap.height()
        
        # Calculer les dimensions selon le format choisi
        formats = {
            "16:9": (16, 9),
            "4:3": (4, 3),
            "1:1": (1, 1),
            "A4": (210, 297),  # mm
            "A3": (297, 420),  # mm
        }
        
        format_name = self.cmb_format.currentText()
        if format_name in formats:
            aspect_w, aspect_h = formats[format_name]
            
            # Calculer les dimensions en préservant la surface
            current_area = current_width * current_height
            new_width = int(np.sqrt(current_area * aspect_w / aspect_h))
            new_height = int(new_width * aspect_h / aspect_w)
            
            # Mettre à jour les champs
            self.txt_width.setText(str(new_width))
            self.txt_height.setText(str(new_height))

    def auto_crop_enabled(self) -> bool:
        """Vérifie si le recadrage auto est activé pour l'export."""
        return self.chk_auto_crop_export.isChecked()

    def get_custom_dimensions(self):
        """Renvoie (largeur, hauteur) si spécifiées, sinon None."""
        try:
            width = int(self.txt_width.text()) if self.txt_width.text() else 0
            height = int(self.txt_height.text()) if self.txt_height.text() else 0
            
            if width > 0 and height > 0:
                return (width, height)
        except ValueError:
            pass
        
        return None
