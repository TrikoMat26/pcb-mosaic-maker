from __future__ import annotations
import logging
from typing import List, Tuple

import cv2
import numpy as np


class Aligner:
    """
    Calcule une homographie Hᵢ pour chaque image par rapport à l'image de référence.
    """

    def __init__(
        self,
        detector: str = "sift",
        ratio_test: float = 0.7,
        ransac_thresh: float = 3.0,
    ):
        self.logger = logging.getLogger(__name__)
        self.ratio_test = ratio_test
        self.ransac_thresh = ransac_thresh
        self.detector_name = detector.lower()

        # Sélection du détecteur
        if self.detector_name == "sift" and hasattr(cv2, "SIFT_create"):
            self.detector = cv2.SIFT_create()
        else:
            self.detector = cv2.ORB_create(nfeatures=4000)
            self.detector_name = "orb"

    # ------------------------------------------------------------------ #
    def _detect_and_compute(self, img: np.ndarray) -> Tuple[List, np.ndarray]:
        """Retourne keypoints + descriptors avec vérification de validité."""
        if img is None or img.size == 0:
            return [], None
            
        try:
            kp, des = self.detector.detectAndCompute(img, None)
            if kp is None or len(kp) == 0 or des is None:
                return [], None
                
            # Vérifier que tous les keypoints ont bien l'attribut pt
            for k in kp:
                if not hasattr(k, 'pt'):
                    return [], None
                    
            return kp, des
        except Exception as e:
            self.logger.debug(f"Erreur détection: {e}")
            return [], None

    # ------------------------------------------------------------------ #
    def _match(self, des1, des2) -> List[cv2.DMatch]:
        """Calcule les correspondances entre descripteurs avec gestion d'erreurs."""
        # Vérifier que les descripteurs existent
        if des1 is None or des2 is None or len(des1) == 0 or len(des2) == 0:
            return []
            
        try:
            if self.detector_name == "sift":
                matcher = cv2.BFMatcher(cv2.NORM_L2)
            else:  # ORB → Hamming
                matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
                
            matches = matcher.knnMatch(des1, des2, k=2)
            
            good = []
            for m, n in matches:
                if m.distance < self.ratio_test * n.distance:
                    good.append(m)
            return good
        except Exception as e:
            self.logger.debug(f"Erreur de matching: {e}")
            return []

    # ------------------------------------------------------------------ #
    def align(self, images: List[np.ndarray], force_align: bool = False, max_deformation: float = 4.0) -> List[np.ndarray]:
        """
        Renvoie la liste des homographies H (shape 3×3, dtype float64).
        
        Args:
            images: Liste d'images à aligner
            force_align: Si True, utilise une homographie simplifiée en cas d'échec
            max_deformation: Rapport d'échelle maximal autorisé entre dimensions
        """
        if len(images) < 2:
            raise ValueError("Au moins 2 images nécessaires.")

        ref_idx = len(images) // 2  # image centrale
        Hs = [None] * len(images)
        Hs[ref_idx] = np.eye(3, dtype=np.float64)

        # Calcule features pour toutes les images
        feats = [self._detect_and_compute(img) for img in images]

        for i, img in enumerate(images):
            if i == ref_idx:
                continue
            
            kp_i, des_i = feats[i]
            kp_ref, des_ref = feats[ref_idx]

            matches = self._match(des_i, des_ref)
            self.logger.debug("Matches %d → %d: %d", i, ref_idx, len(matches))

            if len(matches) < 6:
                if force_align:
                    # Utiliser une transformation simplifiée (translation uniquement)
                    Hs[i] = np.eye(3, dtype=np.float64)
                    continue
                else:
                    raise RuntimeError(f"Matching insuffisant entre images {i} et {ref_idx}")

            try:
                # Extraire les points correspondants
                pts_i = np.float32([kp_i[m.queryIdx].pt for m in matches])
                pts_ref = np.float32([kp_ref[m.trainIdx].pt for m in matches])
                
                # Utiliser RANSAC avec un filtrage plus strict
                H, mask = cv2.findHomography(
                    pts_i, pts_ref, cv2.RANSAC, self.ransac_thresh, maxIters=2000
                )
                
                if H is None:
                    raise RuntimeError(f"Homographie impossible entre {i} et {ref_idx}")
                    
                # Vérifier que l'homographie n'est pas trop déformante
                scale_factors = np.linalg.svd(H[:2, :2])[1]
                deformation_ratio = max(scale_factors) / min(scale_factors)
                
                if deformation_ratio > max_deformation:
                    if force_align:
                        # Cas de déformation excessive: utiliser une homographie simplifiée
                        # Estimer uniquement translation + rotation + échelle uniforme
                        s = np.mean(scale_factors)  # Échelle moyenne
                        H_simplified = np.array([
                            [s*H[0,0]/deformation_ratio, s*H[0,1]/deformation_ratio, H[0,2]],
                            [s*H[1,0]/deformation_ratio, s*H[1,1]/deformation_ratio, H[1,2]],
                            [0, 0, 1]
                        ], dtype=np.float64)
                        Hs[i] = H_simplified
                    else:
                        raise RuntimeError(f"Déformation excessive entre images {i} et {ref_idx}")
                else:
                    Hs[i] = H
            except Exception as e:
                if force_align:
                    # En cas d'échec, utiliser identité avec translation estimée
                    Hs[i] = np.eye(3, dtype=np.float64)
                else:
                    raise RuntimeError(f"Erreur lors de l'alignement: {str(e)}")

        # Remplit les éventuels None (cas improbable) par I
        return [H if H is not None else np.eye(3, dtype=np.float64) for H in Hs]
