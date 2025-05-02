from __future__ import annotations
import numpy as np
import os
import cv2
from pathlib import Path
from typing import List
from PIL import Image

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QFileDialog,
    QMessageBox,
    QWidget,
    QHBoxLayout,
    QProgressDialog,
    QComboBox,
    QLabel,
    QSplitter,
)
from PySide6.QtGui import QIcon

from ..core.loader import ImageLoader
from pcbmosaic.core.aligner import Aligner
from pcbmosaic.core.stitcher import Stitcher
from pcbmosaic.core.exporter import Exporter
from pcbmosaic.gui.canvas_view import CanvasView
from pcbmosaic.gui.tools_panel import ToolsPanel


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PCB-Mosaic-Maker")
        self.resize(1200, 700)
        self.setWindowIcon(QIcon.fromTheme("applications-graphics"))

        self.loader = ImageLoader()
        self.aligner = Aligner()
        self.stitcher = Stitcher()
        self.exporter = Exporter()

        self._build_ui()

        self.images_data: List[dict] = []
        self.homographies = []

    # ------------------------------------------------------------------ #
    def _build_ui(self):
        self.canvas = CanvasView()
        self.tools = ToolsPanel()

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.canvas)
        splitter.addWidget(self.tools)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)

        central = QWidget()
        lay = QHBoxLayout(central)
        lay.addWidget(splitter)
        self.setCentralWidget(central)

        self._create_actions()
        self._create_menus()

    # -------------------------- actions/menus ------------------------- #
    def _create_actions(self):
        from PySide6.QtGui import QAction

        self.act_open = QAction("&Ouvrir…", self)
        self.act_open.triggered.connect(self.open_images)

        self.act_export = QAction("&Exporter JPEG…", self)
        self.act_export.triggered.connect(self.export_mosaic)
        self.act_export.setEnabled(False)

        self.act_quit = QAction("&Quitter", self)
        self.act_quit.triggered.connect(QApplication.quit)

    def _create_menus(self):
        m_file = self.menuBar().addMenu("&Fichier")
        m_file.addAction(self.act_open)
        m_file.addAction(self.act_export)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)

    # ----------------------------- slots ----------------------------- #
    def open_images(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Choisir 2 à 10 photos",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.tif *.tiff)",
        )
        if not paths:
            return
        try:
            self.images_data = self.loader.load(paths)
        except Exception as e:
            QMessageBox.critical(self, "Erreur chargement", str(e))
            return

        # Alignement (progress dialog)
        pd = QProgressDialog(
            "Alignement automatique…", "Annuler", 0, 0, self, Qt.WindowTitleHint
        )
        pd.setWindowModality(Qt.WindowModal)
        pd.show()
        QApplication.processEvents()
        try:
            imgs = [d["image"] for d in self.images_data]
            self.homographies = self.aligner.align(imgs)
        except Exception as e:
            QMessageBox.critical(self, "Alignement impossible", str(e))
            pd.close()
            return
        pd.close()

        # after successful auto‑align preview
        self.canvas.set_preview(imgs, self.homographies)
        self.canvas.prepare_manual(imgs, self.homographies)   # NEW
        self.tools.set_canvas(self.canvas, [d["path"] for d in self.images_data])

    # ------------------------------------------------------------------ #
    def export_mosaic(self):
        if not self.images_data or not self.homographies:
            return

        scale = self.tools.output_scale()
        fmt = "JPEG (*.jpg *.jpeg)"
        outfile, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer la mosaïque", str(Path.home() / "mosaic.jpg"), fmt
        )
        if not outfile:
            return

        pd = QProgressDialog("Fusion haute définition…", None, 0, 0, self)
        pd.setWindowModality(Qt.WindowModal)
        pd.show()
        QApplication.processEvents()

        # Charger les images en haute résolution
        imgs_full = []
        for d in self.images_data:
            path   = d["path"]
            orient = d["meta"].get("Orientation", 1)

            # ouvrir en PIL pour appliquer la même rotation qu'en vignette
            pil = Image.open(path)
            pil = ImageLoader._apply_orientation(pil, orient)

            img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
            imgs_full.append(img)

        # Vérifier que toutes les images ont été chargées
        if len(imgs_full) != len(self.homographies):
            QMessageBox.critical(self, "Erreur", "Nombre d'images et d'homographies différent")
            pd.close()
            return

        # Créer la mosaïque
        try:
            # facteur d’échelle de l’image de référence
            ref_idx = len(self.images_data) // 2
            thumb_ref = self.images_data[ref_idx]["image"]
            full_ref  = imgs_full[ref_idx]
            s_ref = full_ref.shape[1] / thumb_ref.shape[1]          # largeur

            H_full = []
            for i, Ht in enumerate(self.homographies):
                thumb = self.images_data[i]["image"]
                full  = imgs_full[i]
                s_i = full.shape[1] / thumb.shape[1]

                S_ref   = np.diag([s_ref, s_ref, 1.0])
                S_i_inv = np.diag([1 / s_i, 1 / s_i, 1.0])

                H_full.append(S_ref @ Ht @ S_i_inv)

            H_for_export = self.canvas.final_homographies()   # includes manual deltas
            mosaic = self.stitcher.stitch(imgs_full, H_for_export, scale=scale)

        except Exception as e:
            QMessageBox.critical(self, "Erreur fusion", str(e))
            pd.close()
            return
        
        try:
            self.exporter.save(mosaic, outfile)
        except Exception as e:
            QMessageBox.critical(self, "Erreur export", str(e))
            pd.close()
            return
        pd.close()
        QMessageBox.information(self, "Terminé", f"Mosaïque enregistrée :\n{outfile}")


def main():
    from PySide6.QtWidgets import QApplication
    import sys
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
