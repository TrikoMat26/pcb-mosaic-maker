"""
Comparator
~~~~~~~~~~
Compare une mosaïque de PCB « inspecté » à une mosaïque de PCB « référence »
et produit un masque de défauts ainsi qu'une liste de zones suspectes.

Pipeline :

    [reference, inspected]
            |
            v
    [registration ECC]              <- aligne `inspected` sur `reference`
            |
            v
    [égalisation d'éclairage]       <- LAB + CLAHE pour neutraliser les
                                       variations d'expo / balance des blancs
            |
            v
    [diff multi-canaux]             <- combine ΔL, Δgradient, Δstructure
            |
            v
    [seuillage + morphologie]       <- masque binaire propre
            |
            v
    [contours + scoring]            <- liste de défauts (bbox, sévérité)

Le module ne dépend que de OpenCV, NumPy et scikit-image — aucun couplage
avec la GUI.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np
from skimage.metrics import structural_similarity as ssim


# --------------------------------------------------------------------------- #
# Données
# --------------------------------------------------------------------------- #
@dataclass
class Defect:
    """Une zone suspecte trouvée par la comparaison."""

    id: int
    bbox: Tuple[int, int, int, int]       # (x, y, w, h) sur la référence
    centroid: Tuple[int, int]             # (cx, cy)
    area_px: int
    severity: float                       # 0.0 (faible) → 1.0 (critique)
    mean_diff: float                      # intensité moyenne de la diff dans la zone

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "bbox": list(self.bbox),
            "centroid": list(self.centroid),
            "area_px": int(self.area_px),
            "severity": float(self.severity),
            "mean_diff": float(self.mean_diff),
        }


@dataclass
class CompareResult:
    """Sortie complète d'une comparaison."""

    aligned_inspected: np.ndarray         # `inspected` recalé sur la référence
    diff_map: np.ndarray                  # diff continue (uint8, 0..255)
    defect_mask: np.ndarray               # masque binaire (uint8, 0/255)
    defects: List[Defect] = field(default_factory=list)
    homography: Optional[np.ndarray] = None  # H telle que inspected ≈ ref


# --------------------------------------------------------------------------- #
# Comparator
# --------------------------------------------------------------------------- #
class Comparator:
    """
    Compare deux PCB déjà mis en mosaïque.

    Paramètres :

    - ``ecc_iterations`` : itérations max de l'alignement ECC.
    - ``ecc_eps`` : tolérance d'arrêt ECC.
    - ``min_defect_area`` : surface minimum d'un blob retenu (en pixels).
    - ``severity_area_ref`` : surface (px) qui sert de "1.0" à la sévérité.
    - ``thresh_strategy`` : "otsu" (auto) ou "fixed".
    - ``fixed_threshold`` : seuil fixe (0..255) si ``thresh_strategy='fixed'``.
    """

    def __init__(
        self,
        ecc_iterations: int = 200,
        ecc_eps: float = 1e-5,
        min_defect_area: int = 60,
        severity_area_ref: int = 8000,
        thresh_strategy: str = "otsu",
        fixed_threshold: int = 35,
    ):
        self.logger = logging.getLogger(__name__)
        self.ecc_iterations = ecc_iterations
        self.ecc_eps = ecc_eps
        self.min_defect_area = min_defect_area
        self.severity_area_ref = max(1, severity_area_ref)
        self.thresh_strategy = thresh_strategy
        self.fixed_threshold = int(np.clip(fixed_threshold, 1, 254))

    # ------------------------------------------------------------------ #
    #  Étape 1 — Registration ECC
    # ------------------------------------------------------------------ #
    def _register(
        self,
        reference: np.ndarray,
        inspected: np.ndarray,
        warp_mode: int = cv2.MOTION_HOMOGRAPHY,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """
        Aligne ``inspected`` sur ``reference`` avec ``cv2.findTransformECC``.

        Retourne (inspected_aligned, H_3x3).  Si ECC échoue, retombe sur
        une registration par features ORB en secours.
        """
        ref_gray = cv2.cvtColor(reference, cv2.COLOR_BGR2GRAY)
        ins_gray = cv2.cvtColor(inspected, cv2.COLOR_BGR2GRAY)

        # ECC est bien plus stable sur des images préfiltrées
        ref_blur = cv2.GaussianBlur(ref_gray, (5, 5), 1.0)
        ins_blur = cv2.GaussianBlur(ins_gray, (5, 5), 1.0)

        if warp_mode == cv2.MOTION_HOMOGRAPHY:
            warp = np.eye(3, 3, dtype=np.float32)
        else:
            warp = np.eye(2, 3, dtype=np.float32)

        criteria = (
            cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT,
            self.ecc_iterations,
            self.ecc_eps,
        )

        try:
            _cc, warp = cv2.findTransformECC(
                ref_blur, ins_blur, warp, warp_mode, criteria, None, 5
            )
        except cv2.error as e:
            self.logger.warning("ECC failed (%s) — falling back to ORB", e)
            warp = self._register_orb(ref_gray, ins_gray)
            warp_mode = cv2.MOTION_HOMOGRAPHY

        h, w = reference.shape[:2]
        if warp_mode == cv2.MOTION_HOMOGRAPHY:
            aligned = cv2.warpPerspective(
                inspected, warp, (w, h),
                flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP,
                borderMode=cv2.BORDER_REPLICATE,
            )
            H = warp.astype(np.float64)
        else:
            aligned = cv2.warpAffine(
                inspected, warp, (w, h),
                flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP,
                borderMode=cv2.BORDER_REPLICATE,
            )
            H = np.vstack([warp.astype(np.float64), [0.0, 0.0, 1.0]])

        return aligned, H

    @staticmethod
    def _register_orb(ref_gray: np.ndarray, ins_gray: np.ndarray) -> np.ndarray:
        """Fallback de secours par features ORB."""
        orb = cv2.ORB_create(nfeatures=4000)
        kp1, des1 = orb.detectAndCompute(ref_gray, None)
        kp2, des2 = orb.detectAndCompute(ins_gray, None)
        if des1 is None or des2 is None:
            return np.eye(3, dtype=np.float32)

        bf = cv2.BFMatcher(cv2.NORM_HAMMING)
        raw = bf.knnMatch(des2, des1, k=2)
        good = [m for m, n in raw if m.distance < 0.8 * n.distance]
        if len(good) < 8:
            return np.eye(3, dtype=np.float32)

        src = np.float32([kp2[m.queryIdx].pt for m in good])
        dst = np.float32([kp1[m.trainIdx].pt for m in good])
        H, _ = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
        if H is None:
            return np.eye(3, dtype=np.float32)
        return H.astype(np.float32)

    # ------------------------------------------------------------------ #
    #  Étape 2 — Diff tolérant aux variations d'éclairage
    # ------------------------------------------------------------------ #
    @staticmethod
    def _equalize_lab(img: np.ndarray) -> np.ndarray:
        """CLAHE sur le canal L de LAB pour neutraliser l'expo globale."""
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        L, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        L_eq = clahe.apply(L)
        return cv2.merge([L_eq, a, b])

    def _diff_map(
        self, reference: np.ndarray, aligned: np.ndarray
    ) -> np.ndarray:
        """
        Diff combinée :
        - Δ chrominance (canaux a, b de LAB) : robuste aux variations d'expo.
        - Δ structure (SSIM inversé) : capture les disparitions de motifs.

        Le résultat est un uint8 où plus c'est clair, plus c'est suspect.
        """
        ref_lab = self._equalize_lab(reference)
        ins_lab = self._equalize_lab(aligned)

        # 1) Différence sur a + b (couleur, indépendant de la luminance)
        diff_ab = cv2.absdiff(ref_lab[..., 1:], ins_lab[..., 1:])
        diff_ab = diff_ab.astype(np.float32).max(axis=2)  # max sur a et b

        # 2) Différence structurelle (SSIM) sur la luminance égalisée
        ref_l = ref_lab[..., 0].astype(np.float32) / 255.0
        ins_l = ins_lab[..., 0].astype(np.float32) / 255.0
        win = 7 if min(ref_l.shape) >= 7 else 3
        _score, ssim_map = ssim(
            ref_l, ins_l, win_size=win, full=True, data_range=1.0
        )
        struct_diff = (1.0 - ssim_map) * 255.0  # plus c'est différent, plus c'est clair

        # Combinaison pondérée — la chrominance domine sur les soudures /
        # composants manquants, la structure capture les pistes coupées.
        combined = 0.55 * struct_diff + 0.45 * diff_ab
        combined = np.clip(combined, 0, 255).astype(np.uint8)

        # Lissage léger pour éviter le bruit de pixel isolé
        return cv2.medianBlur(combined, 3)

    # ------------------------------------------------------------------ #
    #  Étape 3 — Masque + contours scorés
    # ------------------------------------------------------------------ #
    def _binarize(self, diff: np.ndarray) -> np.ndarray:
        """Seuillage du diff_map en masque binaire 0/255."""
        if self.thresh_strategy == "fixed":
            _, mask = cv2.threshold(diff, self.fixed_threshold, 255, cv2.THRESH_BINARY)
        else:
            _, mask = cv2.threshold(
                diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
            )

        # Ferme les petits trous, supprime le bruit
        k3 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        k5 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k3, iterations=1)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k5, iterations=2)
        return mask

    def _extract_defects(
        self, mask: np.ndarray, diff: np.ndarray
    ) -> List[Defect]:
        """Contours connectés → liste de Defect ordonnés par sévérité décroissante."""
        n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
            mask, connectivity=8
        )
        defects: List[Defect] = []
        # label 0 = fond
        for lbl in range(1, n_labels):
            x, y, w, h, area = stats[lbl]
            if area < self.min_defect_area:
                continue
            cx, cy = centroids[lbl]
            roi_diff = diff[y:y + h, x:x + w]
            roi_mask = labels[y:y + h, x:x + w] == lbl
            if not roi_mask.any():
                continue
            mean_d = float(roi_diff[roi_mask].mean())
            # Sévérité : mélange surface relative + intensité
            sev = min(1.0, 0.6 * (area / self.severity_area_ref) + 0.4 * (mean_d / 255.0))
            defects.append(
                Defect(
                    id=0,  # ré-affecté plus bas
                    bbox=(int(x), int(y), int(w), int(h)),
                    centroid=(int(cx), int(cy)),
                    area_px=int(area),
                    severity=float(sev),
                    mean_diff=mean_d,
                )
            )

        defects.sort(key=lambda d: d.severity, reverse=True)
        for i, d in enumerate(defects, start=1):
            d.id = i
        return defects

    # ------------------------------------------------------------------ #
    #  API publique
    # ------------------------------------------------------------------ #
    def compare(
        self, reference: np.ndarray, inspected: np.ndarray
    ) -> CompareResult:
        """Retourne un :class:`CompareResult` complet."""
        if reference is None or inspected is None:
            raise ValueError("reference et inspected doivent être non-nuls")
        if reference.ndim != 3 or inspected.ndim != 3:
            raise ValueError("Les images doivent être en BGR (3 canaux).")

        # Si les tailles divergent, on harmonise sur la référence ; ECC
        # exigerait sinon des affines trop importantes.
        if inspected.shape[:2] != reference.shape[:2]:
            inspected = cv2.resize(
                inspected,
                (reference.shape[1], reference.shape[0]),
                interpolation=cv2.INTER_AREA,
            )

        aligned, H = self._register(reference, inspected)
        diff = self._diff_map(reference, aligned)
        mask = self._binarize(diff)
        defects = self._extract_defects(mask, diff)

        return CompareResult(
            aligned_inspected=aligned,
            diff_map=diff,
            defect_mask=mask,
            defects=defects,
            homography=H,
        )

    # ------------------------------------------------------------------ #
    #  Rendu utilitaire
    # ------------------------------------------------------------------ #
    @staticmethod
    def render_overlay(
        reference: np.ndarray,
        result: CompareResult,
        alpha: float = 0.45,
        draw_boxes: bool = True,
    ) -> np.ndarray:
        """
        Compose la référence + un voile rouge sur les défauts + bbox.
        Renvoie une image BGR prête à afficher.
        """
        out = reference.copy()
        red = np.zeros_like(reference)
        red[..., 2] = 255  # canal rouge en BGR
        m = (result.defect_mask > 0)
        if m.any():
            out[m] = (
                (1 - alpha) * out[m].astype(np.float32)
                + alpha * red[m].astype(np.float32)
            ).astype(np.uint8)

        if draw_boxes:
            for d in result.defects:
                x, y, w, h = d.bbox
                # Couleur = vert (faible) → jaune → rouge selon sévérité
                hue = int((1.0 - d.severity) * 60)  # 60 = vert, 0 = rouge en HSV
                bgr = cv2.cvtColor(
                    np.uint8([[[hue, 255, 255]]]), cv2.COLOR_HSV2BGR
                )[0, 0].tolist()
                cv2.rectangle(out, (x, y), (x + w, y + h), bgr, 2)
                label = f"#{d.id} {d.severity:.2f}"
                cv2.putText(
                    out, label, (x, max(0, y - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, bgr, 1, cv2.LINE_AA
                )
        return out
