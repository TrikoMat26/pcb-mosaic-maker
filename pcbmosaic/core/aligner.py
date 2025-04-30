from __future__ import annotations
import logging
from typing import List

import cv2
import numpy as np


class Aligner:
    """
    Calcule une homographie Hᵢ pour chaque image par rapport à l'image de référence.
    """

    def __init__(
        self,
        detector: str = "sift",
        ratio_test: float = 0.7,  # Valeur plus stricte pour de meilleurs matches
        ransac_thresh: float = 3.0,  # Valeur plus stricte pour de meilleures homographies
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
    def _detect_and_compute(self, img: np.ndarray):
        """Retourne keypoints + descriptors."""
        kp, des = self.detector.detectAndCompute(img, None)
        return kp, des

    # ------------------------------------------------------------------ #
    def _match(self, des1, des2) -> List[cv2.DMatch]:
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

    # ------------------------------------------------------------------ #
    def align(self, images: List[np.ndarray]) -> List[np.ndarray]:
        """
        Renvoie la liste des homographies H (shape 3×3, dtype float64) ;
        H[0] == I (image de référence).
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
                raise RuntimeError(f"Matching insuffisant entre images {i} et {ref_idx}")

            pts_i = np.float32([kp_i[m.queryIdx].pt for m in matches])
            pts_ref = np.float32([kp_ref[m.trainIdx].pt for m in matches])

            H, mask = cv2.findHomography(
                pts_i, pts_ref, cv2.RANSAC, self.ransac_thresh
            )
            if H is None:
                raise RuntimeError(f"Homographie impossible entre {i} et {ref_idx}")
            Hs[i] = H

        # Remplit les éventuels None (cas improbable) par I
        return [H if H is not None else np.eye(3, dtype=np.float64) for H in Hs]
