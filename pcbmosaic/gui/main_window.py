"""
MainWindow — fenêtre Qt principale.

Workflow supporté :

1. *Référence*    : ouvrir 2..10 photos d'un PCB → alignement automatique →
                    placement des photos comme objets librement déplaçables
                    → ``Définir comme référence`` génère la mosaïque pleine
                    résolution et la mémorise.
2. *Inspection*   : charger un PCB inspecté (image déjà assemblée OU série
                    de photos à assembler) → ``Lancer comparaison``.
3. *Comparaison*  : registration ECC + diff tolérant à l'éclairage →
                    overlay rouge sur la référence + liste de défauts.
4. *Export*       : mosaïque référence (JPEG), overlay annoté (JPEG),
                    rapport JSON des défauts.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QProgressDialog,
    QSplitter,
    QWidget,
)

from ..core.loader import ImageLoader
from ..core.aligner import Aligner
from ..core.stitcher import Stitcher
from ..core.exporter import Exporter
from ..core.comparator import Comparator, CompareResult
from .canvas_view import CanvasView
from .tools_panel import ToolsPanel
from .click_align_dialog import ClickAlignDialog


# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PCB-Mosaic-Maker")
        self.resize(1280, 800)
        self.setWindowIcon(QIcon.fromTheme("applications-graphics"))

        # Pipeline objects
        self.loader = ImageLoader()
        self.aligner = Aligner(detector="phase")
        self.stitcher = Stitcher()
        self.exporter = Exporter()
        self.comparator = Comparator()

        # State
        self.images_data: List[dict] = []
        self.homographies: List[np.ndarray] = []
        self.reference_mosaic: Optional[np.ndarray] = None
        self.inspected_mosaic: Optional[np.ndarray] = None
        self.compare_result: Optional[CompareResult] = None
        # Clics persistants de l'alignement par clics : rouvrir le dialog
        # repart de cet état au lieu d'une feuille blanche.
        self.saved_pair_clicks: Optional[
            List[List[Tuple[Tuple[float, float], Tuple[float, float]]]]
        ] = None

        self._build_ui()

    # ------------------------------------------------------------------ #
    #  UI
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        self.canvas = CanvasView()
        self.tools = ToolsPanel()

        self.tools.alignerModeChanged.connect(self._on_aligner_mode_changed)
        self.tools.defectSelected.connect(self.canvas.focus_defect)
        self.tools.resetPositionsRequested.connect(self.canvas.reset_all_positions)
        self.tools.photoOrderChanged.connect(self._on_photo_order_changed)

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
        self._create_statusbar()

    def _create_actions(self):
        self.act_open = QAction("&Ouvrir des photos…", self)
        self.act_open.triggered.connect(self.open_images)
        self.act_open.setShortcut("Ctrl+O")

        self.act_add = QAction("&Ajouter des photos…", self)
        self.act_add.triggered.connect(self.add_photos)
        self.act_add.setShortcut("Ctrl+Shift+O")
        self.act_add.setEnabled(False)

        self.act_rotate_sel_cw = QAction("Pivoter la sélection ↻ 90°", self)
        self.act_rotate_sel_cw.triggered.connect(lambda: self._rotate_selection(90))
        self.act_rotate_sel_cw.setShortcut("Ctrl+R")
        self.act_rotate_sel_cw.setEnabled(False)

        self.act_rotate_sel_ccw = QAction("Pivoter la sélection ↺ 90°", self)
        self.act_rotate_sel_ccw.triggered.connect(lambda: self._rotate_selection(-90))
        self.act_rotate_sel_ccw.setShortcut("Ctrl+Shift+R")
        self.act_rotate_sel_ccw.setEnabled(False)

        self.act_rotate_sel_180 = QAction("Pivoter la sélection 180°", self)
        self.act_rotate_sel_180.triggered.connect(lambda: self._rotate_selection(180))
        self.act_rotate_sel_180.setEnabled(False)

        self.act_rotate_all_cw = QAction("Pivoter toutes les photos ↻ 90°", self)
        self.act_rotate_all_cw.triggered.connect(lambda: self._rotate_all(90))
        self.act_rotate_all_cw.setEnabled(False)

        self.act_rotate_all_ccw = QAction("Pivoter toutes les photos ↺ 90°", self)
        self.act_rotate_all_ccw.triggered.connect(lambda: self._rotate_all(-90))
        self.act_rotate_all_ccw.setEnabled(False)

        self.act_export_ref = QAction("Exporter la mosaïque (&JPEG)…", self)
        self.act_export_ref.triggered.connect(self.export_mosaic)
        self.act_export_ref.setEnabled(False)

        self.act_set_ref = QAction("Définir comme &référence", self)
        self.act_set_ref.triggered.connect(self.set_as_reference)
        self.act_set_ref.setEnabled(False)

        self.act_click_align = QAction("Aligner par &clics…", self)
        self.act_click_align.triggered.connect(self.run_click_align)
        self.act_click_align.setEnabled(False)
        self.act_click_align.setShortcut("Ctrl+L")

        self.act_load_inspected_img = QAction("Charger un PCB inspecté (&image)…", self)
        self.act_load_inspected_img.triggered.connect(self.load_inspected_image)
        self.act_load_inspected_img.setEnabled(False)

        self.act_load_inspected_photos = QAction("Charger des photos d'un PCB inspecté…", self)
        self.act_load_inspected_photos.triggered.connect(self.load_inspected_photos)
        self.act_load_inspected_photos.setEnabled(False)

        self.act_run_compare = QAction("&Lancer la comparaison", self)
        self.act_run_compare.triggered.connect(self.run_compare)
        self.act_run_compare.setEnabled(False)
        self.act_run_compare.setShortcut("F5")

        self.act_export_overlay = QAction("Exporter l'overlay des défauts…", self)
        self.act_export_overlay.triggered.connect(self.export_overlay)
        self.act_export_overlay.setEnabled(False)

        self.act_export_report = QAction("Exporter le rapport JSON…", self)
        self.act_export_report.triggered.connect(self.export_report_json)
        self.act_export_report.setEnabled(False)

        self.act_quit = QAction("&Quitter", self)
        self.act_quit.triggered.connect(QApplication.quit)
        self.act_quit.setShortcut("Ctrl+Q")

    def _create_menus(self):
        m_file = self.menuBar().addMenu("&Fichier")
        m_file.addAction(self.act_open)
        m_file.addAction(self.act_add)
        m_file.addAction(self.act_export_ref)
        m_file.addSeparator()
        m_file.addAction(self.act_quit)

        m_photos = self.menuBar().addMenu("&Photos")
        m_photos.addAction(self.act_rotate_sel_cw)
        m_photos.addAction(self.act_rotate_sel_ccw)
        m_photos.addAction(self.act_rotate_sel_180)
        m_photos.addSeparator()
        m_photos.addAction(self.act_rotate_all_cw)
        m_photos.addAction(self.act_rotate_all_ccw)

        m_ref = self.menuBar().addMenu("&Référence")
        m_ref.addAction(self.act_click_align)
        m_ref.addSeparator()
        m_ref.addAction(self.act_set_ref)

        m_cmp = self.menuBar().addMenu("&Comparaison")
        m_cmp.addAction(self.act_load_inspected_img)
        m_cmp.addAction(self.act_load_inspected_photos)
        m_cmp.addSeparator()
        m_cmp.addAction(self.act_run_compare)
        m_cmp.addSeparator()
        m_cmp.addAction(self.act_export_overlay)
        m_cmp.addAction(self.act_export_report)

    def _create_statusbar(self):
        self.statusBar().showMessage("Prêt.")

    # ------------------------------------------------------------------ #
    #  Slots — Référence
    # ------------------------------------------------------------------ #
    def open_images(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Choisir 2 à 10 photos d'un PCB",
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

        # Nouveau lot : on oublie les clics d'un éventuel lot précédent
        self.saved_pair_clicks = None

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

        # Affiche chaque photo comme un objet déplaçable
        self.canvas.prepare_items(imgs, self.homographies)
        self.tools.set_canvas(self.canvas, [d["path"] for d in self.images_data])

        self._enable_photo_actions(True)
        self.statusBar().showMessage(
            f"{len(self.images_data)} photos chargées (mode {self.aligner.detector_name}). "
            "Glisse une photo à la souris pour l'ajuster, ou Référence > Aligner par clics."
        )

    def add_photos(self):
        """Ajoute des photos en préservant l'alignement déjà fait.

        Les photos existantes (et leurs ajustements manuels / par clics)
        ne sont **pas** retouchées. Chaque nouvelle photo est alignée par
        paire successive en partant de la dernière photo existante, et son
        homographie est chaînée vers le repère global déjà établi.
        """
        if not self.images_data:
            return self.open_images()

        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Ajouter des photos (peut être dans un autre dossier)",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.tif *.tiff)",
        )
        if not paths:
            return

        # Snapshot pour rollback en cas d'échec
        old_images_data = list(self.images_data)
        old_homographies = list(self.homographies)

        try:
            new_data = self.loader.load_more(paths)
        except Exception as e:
            QMessageBox.critical(self, "Erreur chargement", str(e))
            return

        # Récupère les positions courantes du canvas (auto-align + manuel + clics)
        # pour préserver tout le travail de l'utilisateur.
        Hs_existing = self.canvas.current_homographies()
        if len(Hs_existing) != len(old_images_data):
            # Filet de sécurité : si le canvas est dans un état inattendu,
            # on retombe sur les homographies stockées.
            Hs_existing = old_homographies

        pd = QProgressDialog(
            "Alignement des nouvelles photos sur l'existant…",
            None, 0, 0, self,
        )
        pd.setWindowModality(Qt.WindowModal)
        pd.show()
        QApplication.processEvents()

        try:
            # On chaîne chaque nouvelle photo à partir de la dernière.
            # Pour chaque (anchor, new) : aligner.align([new, anchor]) renvoie
            # pair_Hs[0] qui mappe new → anchor (anchor est la ref de la paire,
            # placé en position d'index ref_idx=1).
            Hs_new: List[np.ndarray] = []
            anchor_img = old_images_data[-1]["image"]
            anchor_H = Hs_existing[-1]
            for d in new_data:
                new_img = d["image"]
                pair_Hs = self.aligner.align([new_img, anchor_img])
                H_to_anchor = pair_Hs[0]              # new → anchor
                H_new = anchor_H @ H_to_anchor        # new → ref global
                Hs_new.append(H_new)
                # La nouvelle photo devient l'ancre pour la suivante
                anchor_img = new_img
                anchor_H = H_new
        except Exception as e:
            pd.close()
            self.images_data = old_images_data
            self.homographies = old_homographies
            QMessageBox.critical(
                self,
                "Alignement impossible",
                f"L'alignement de la nouvelle photo a échoué :\n{e}\n\n"
                "Les photos précédentes sont conservées. Essaie un autre mode "
                "d'alignement (SIFT/ORB) ou Aligner par clics après ajout.",
            )
            return
        pd.close()

        # Tout s'est bien passé : on commit les nouveaux états
        self.images_data.extend(new_data)
        self.homographies = list(Hs_existing) + Hs_new

        try:
            imgs = [d["image"] for d in self.images_data]
            self.canvas.prepare_items(imgs, self.homographies)
            self.tools.set_canvas(self.canvas, [d["path"] for d in self.images_data])
        except Exception as e:
            self.images_data = old_images_data
            self.homographies = old_homographies
            QMessageBox.critical(self, "Erreur affichage", str(e))
            return

        self.statusBar().showMessage(
            f"{len(self.images_data)} photos au total ({len(new_data)} ajoutées, "
            "alignement existant préservé)."
        )

    def _enable_photo_actions(self, on: bool):
        self.act_export_ref.setEnabled(on)
        self.act_set_ref.setEnabled(on)
        self.act_click_align.setEnabled(on)
        self.act_add.setEnabled(on)
        self.act_rotate_sel_cw.setEnabled(on)
        self.act_rotate_sel_ccw.setEnabled(on)
        self.act_rotate_sel_180.setEnabled(on)
        self.act_rotate_all_cw.setEnabled(on)
        self.act_rotate_all_ccw.setEnabled(on)

    def _rotate_selection(self, deg: int):
        """Pivote la photo sélectionnée sur le canevas de ±90° ou 180°."""
        idx = self.canvas.selected_index()
        if idx is None:
            QMessageBox.information(
                self, "Aucune photo sélectionnée",
                "Clique d'abord sur la photo à pivoter, puis relance l'action.",
            )
            return
        self._rotate_one(idx, deg)

    def _rotate_all(self, deg: int):
        for idx in range(len(self.images_data)):
            self._rotate_one(idx, deg, refresh_canvas=False)
        # Un seul refresh global à la fin
        imgs = [d["image"] for d in self.images_data]
        self.canvas.prepare_items(imgs, self.homographies)
        self.tools.set_canvas(self.canvas, [d["path"] for d in self.images_data])

    def _rotate_one(self, idx: int, deg: int, refresh_canvas: bool = True):
        """Rotation destructive du bitmap d'une photo + maj user_rotation_deg."""
        d = self.images_data[idx]
        img = d["image"]
        if deg == 90:
            img = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
        elif deg == -90:
            img = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif deg == 180:
            img = cv2.rotate(img, cv2.ROTATE_180)
        else:
            return
        d["image"] = img
        d["user_rotation_deg"] = (d.get("user_rotation_deg", 0) + deg) % 360
        if refresh_canvas:
            self.canvas.replace_photo_image(idx, img)

    def run_click_align(self):
        """Ouvre la boîte d'alignement par clics et applique le résultat.

        Restaure les clics de la session précédente si l'utilisateur a déjà
        utilisé ce dialog. Pour les paires sans clics (ex : nouvelle photo
        ajoutée après coup), l'alignement existant du canvas est conservé.
        """
        if not self.images_data:
            return
        imgs = [d["image"] for d in self.images_data]
        names = [str(d["path"]) for d in self.images_data]

        # On peut avoir des clics sauvegardés pour moins de paires que ce
        # qu'on a maintenant (ex : l'utilisateur a ajouté une photo après
        # un premier click-align). Le dialog accepte ce désalignement et
        # initialise les paires manquantes à vide.
        dlg = ClickAlignDialog(
            imgs, names, self,
            initial_pair_clicks=self.saved_pair_clicks,
        )
        # Note : en PySide6 récent, `Accepted` est un membre d'enum de la
        # classe QDialog, pas un attribut d'instance — on le lit donc sur
        # la classe pour éviter `AttributeError`.
        if dlg.exec() != QDialog.Accepted:
            return
        pair_clicks = dlg.get_pair_clicks()

        # Récupère les Hs actuels du canvas comme filet de sécurité : les
        # paires sans clics conservent leur alignement courant au lieu de
        # retomber sur de l'identité.
        existing_Hs = self.canvas.current_homographies()
        if len(existing_Hs) != len(imgs):
            existing_Hs = self.homographies if len(self.homographies) == len(imgs) else None

        try:
            self.homographies = Aligner.align_from_clicks(
                imgs, pair_clicks, fallback_Hs=existing_Hs,
            )
        except Exception as e:
            QMessageBox.critical(self, "Erreur alignement", str(e))
            return

        # Persiste les clics pour la prochaine ouverture du dialog
        self.saved_pair_clicks = pair_clicks

        # Remet les photos en place avec les nouvelles homographies
        self.canvas.prepare_items(imgs, self.homographies)
        self.tools.set_canvas(self.canvas, [d["path"] for d in self.images_data])
        self.statusBar().showMessage(
            "Alignement par clics appliqué. Tu peux encore ajuster à la souris."
        )

    def set_as_reference(self):
        if not self.images_data:
            return
        pd = QProgressDialog(
            "Construction de la mosaïque référence (haute résolution)…",
            None, 0, 0, self,
        )
        pd.setWindowModality(Qt.WindowModal)
        pd.show()
        QApplication.processEvents()
        try:
            self.reference_mosaic = self._build_full_mosaic()
        except Exception as e:
            QMessageBox.critical(self, "Erreur", str(e))
            pd.close()
            return
        pd.close()

        self.act_load_inspected_img.setEnabled(True)
        self.act_load_inspected_photos.setEnabled(True)
        if self.inspected_mosaic is not None:
            self.act_run_compare.setEnabled(True)
        self.statusBar().showMessage(
            f"Référence définie : {self.reference_mosaic.shape[1]}×"
            f"{self.reference_mosaic.shape[0]} px."
        )

    # ------------------------------------------------------------------ #
    #  Slots — Inspection
    # ------------------------------------------------------------------ #
    def load_inspected_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Charger l'image du PCB inspecté",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.tif *.tiff)",
        )
        if not path:
            return
        try:
            pil = Image.open(path)
            try:
                exif = pil.getexif()
                orient = exif.get(0x0112, 1) if exif else 1
                pil = ImageLoader._apply_orientation(pil, orient)
            except Exception:
                pass
            img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
        except Exception as e:
            QMessageBox.critical(self, "Erreur chargement", str(e))
            return

        self.inspected_mosaic = img
        if self.reference_mosaic is not None:
            self.act_run_compare.setEnabled(True)
        self.statusBar().showMessage(
            f"PCB inspecté chargé : {img.shape[1]}×{img.shape[0]} px."
        )

    def load_inspected_photos(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Photos du PCB inspecté (2 à 10)",
            str(Path.home()),
            "Images (*.png *.jpg *.jpeg *.tif *.tiff)",
        )
        if not paths:
            return

        pd = QProgressDialog(
            "Alignement et assemblage du PCB inspecté…", None, 0, 0, self
        )
        pd.setWindowModality(Qt.WindowModal)
        pd.show()
        QApplication.processEvents()
        try:
            data = self.loader.load(paths)
            imgs = [d["image"] for d in data]
            Hs = self.aligner.align(imgs)
            mosaic = self._stitch_full_res(data, Hs)
        except Exception as e:
            pd.close()
            QMessageBox.critical(self, "Erreur", str(e))
            return
        pd.close()

        self.inspected_mosaic = mosaic
        if self.reference_mosaic is not None:
            self.act_run_compare.setEnabled(True)
        self.statusBar().showMessage(
            f"PCB inspecté assemblé : {mosaic.shape[1]}×{mosaic.shape[0]} px."
        )

    # ------------------------------------------------------------------ #
    #  Slots — Comparaison
    # ------------------------------------------------------------------ #
    def run_compare(self):
        if self.reference_mosaic is None or self.inspected_mosaic is None:
            return
        pd = QProgressDialog(
            "Registration ECC et détection des défauts…", None, 0, 0, self
        )
        pd.setWindowModality(Qt.WindowModal)
        pd.show()
        QApplication.processEvents()
        try:
            res = self.comparator.compare(self.reference_mosaic, self.inspected_mosaic)
        except Exception as e:
            pd.close()
            QMessageBox.critical(self, "Erreur comparaison", str(e))
            return
        pd.close()

        self.compare_result = res
        overlay = self.comparator.render_overlay(self.reference_mosaic, res)
        self.canvas.set_compare_overlay(overlay, res)
        self.tools.set_defects(res.defects)

        self.act_export_overlay.setEnabled(True)
        self.act_export_report.setEnabled(True)
        self.statusBar().showMessage(
            f"Comparaison terminée : {len(res.defects)} défauts détectés."
        )

    # ------------------------------------------------------------------ #
    #  Slots — Export
    # ------------------------------------------------------------------ #
    def export_mosaic(self):
        if not self.images_data or not self.homographies:
            return

        outfile, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer la mosaïque",
            str(Path.home() / "mosaic.jpg"),
            "JPEG (*.jpg *.jpeg)",
        )
        if not outfile:
            return

        pd = QProgressDialog("Fusion haute définition…", None, 0, 0, self)
        pd.setWindowModality(Qt.WindowModal)
        pd.show()
        QApplication.processEvents()
        try:
            mosaic = self._build_full_mosaic()
            self.exporter.save(mosaic, outfile)
        except Exception as e:
            pd.close()
            QMessageBox.critical(self, "Erreur export", str(e))
            return
        pd.close()
        QMessageBox.information(self, "Terminé", f"Mosaïque enregistrée :\n{outfile}")

    def export_overlay(self):
        if self.compare_result is None or self.reference_mosaic is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer l'overlay des défauts",
            str(Path.home() / "defects_overlay.jpg"),
            "JPEG (*.jpg *.jpeg);;PNG (*.png)",
        )
        if not path:
            return
        overlay = self.comparator.render_overlay(self.reference_mosaic, self.compare_result)
        try:
            self.exporter.save(overlay, path)
        except Exception as e:
            QMessageBox.critical(self, "Erreur export", str(e))
            return
        QMessageBox.information(self, "Terminé", f"Overlay enregistré :\n{path}")

    def export_report_json(self):
        if self.compare_result is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le rapport JSON",
            str(Path.home() / "defects_report.json"),
            "JSON (*.json)",
        )
        if not path:
            return
        report = {
            "reference_size": list(self.reference_mosaic.shape[:2][::-1])
            if self.reference_mosaic is not None else None,
            "n_defects": len(self.compare_result.defects),
            "defects": [d.as_dict() for d in self.compare_result.defects],
        }
        try:
            Path(path).write_text(json.dumps(report, indent=2), encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "Erreur export", str(e))
            return
        QMessageBox.information(self, "Terminé", f"Rapport enregistré :\n{path}")

    # ------------------------------------------------------------------ #
    #  Helpers
    # ------------------------------------------------------------------ #
    def _on_aligner_mode_changed(self, mode: str):
        self.aligner = Aligner(detector=mode)
        self.statusBar().showMessage(f"Mode d'alignement : {mode}.")

    def _on_photo_order_changed(self, new_order_paths: list):
        """Réordonne les photos sans toucher à leur position géométrique.

        L'utilisateur a réorganisé la liste latérale (drag-drop ou boutons
        ▲/▼). On synchronise les structures internes (``images_data``,
        ``homographies``) avec ce nouvel ordre, puis on reconstruit le
        canvas. Les positions courantes des photos (auto-align + ajustements
        souris) sont **préservées** : seul l'ordre dans la liste change,
        ce qui détermine notamment le chaînage lors d'ajouts ultérieurs.
        """
        if not self.images_data:
            return

        # Récupère les Hs actuels (incluent les ajustements souris) AVANT
        # de toucher à images_data, pour pouvoir les réordonner avec.
        current_Hs = self.canvas.current_homographies()
        if len(current_Hs) != len(self.images_data):
            current_Hs = list(self.homographies)

        old_paths = [str(d["path"]) for d in self.images_data]
        try:
            permutation = [old_paths.index(p) for p in new_order_paths]
        except ValueError:
            # Chemin inconnu : on ignore l'événement (sécurité)
            return
        if permutation == list(range(len(old_paths))):
            return  # ordre inchangé

        # Réordonne en synchronie
        self.images_data = [self.images_data[i] for i in permutation]
        self.homographies = [current_Hs[i] for i in permutation]

        # Les clics sauvegardés portent sur des paires consécutives qui
        # peuvent ne plus exister dans le nouvel ordre → on les efface.
        self.saved_pair_clicks = None

        # Rebuild canvas avec les Hs réordonnés ; la disposition
        # géométrique sur le canvas reste inchangée (chaque photo conserve
        # son homographie globale, donc sa place à l'écran).
        imgs = [d["image"] for d in self.images_data]
        try:
            self.canvas.prepare_items(imgs, self.homographies)
        except Exception as e:
            QMessageBox.critical(self, "Erreur affichage", str(e))
            return

        # NB : on ne rappelle pas tools.set_canvas — la liste latérale
        # affiche déjà le bon ordre puisque c'est elle qui a émis le signal.
        self.statusBar().showMessage(
            f"Ordre des photos modifié ({len(self.images_data)} photos)."
        )

    def _build_full_mosaic(self) -> np.ndarray:
        """Reconstitue la mosaïque en pleine résolution avec les positions courantes."""
        Hs_thumb = self.canvas.current_homographies()  # auto-align + ajustements souris
        return self._stitch_full_res(self.images_data, Hs_thumb, use_thumb_homographies=True)

    def _stitch_full_res(
        self,
        images_data: List[dict],
        homographies: List[np.ndarray],
        use_thumb_homographies: bool = False,
    ) -> np.ndarray:
        """
        Recharge les images en pleine résolution puis applique le stitching.

        Si ``use_thumb_homographies`` est True, les homographies fournies
        sont en pixels vignettes et on les reprojette en pleine résolution.
        """
        imgs_full: List[np.ndarray] = []
        for d in images_data:
            imgs_full.append(
                ImageLoader.reload_full_res(
                    d["path"], d.get("user_rotation_deg", 0)
                )
            )

        if use_thumb_homographies:
            ref_idx = len(images_data) // 2
            full_w_ref = imgs_full[ref_idx].shape[1]
            thumb_w_ref = images_data[ref_idx]["image"].shape[1]
            s_ref = full_w_ref / thumb_w_ref

            H_full: List[np.ndarray] = []
            for i, Ht in enumerate(homographies):
                full_w = imgs_full[i].shape[1]
                thumb_w = images_data[i]["image"].shape[1]
                s_i = full_w / thumb_w
                S_ref = np.diag([s_ref, s_ref, 1.0])
                S_i_inv = np.diag([1.0 / s_i, 1.0 / s_i, 1.0])
                H_full.append(S_ref @ Ht @ S_i_inv)
        else:
            H_full = homographies

        scale = self.tools.output_scale()
        return self.stitcher.stitch(imgs_full, H_full, scale=scale)


# --------------------------------------------------------------------------- #
def main():
    import sys

    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
