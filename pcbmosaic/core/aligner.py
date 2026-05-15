# aligner.py — phase correlation + features (SIFT/ORB) backends
"""
Aligner
~~~~~~~
Calcule une homographie 3x3 pour chaque image par rapport a une image de
reference (par defaut, l'image mediane).

Trois strategies sont disponibles :

- ``"phase"``   (recommandee pour les PCB pris selon la meme incidence)
                phase correlation par paires successives, robuste aux
                surfaces peu texturees et repetitives ; restreint au modele
                translation 2D, ce qui est en pratique le bon modele pour
                des photos macro / microscope.
- ``"sift"``    detection SIFT + RANSAC (homographie complete) ;
                fonctionne mal sur les builds OpenCV.js mais reste solide
                en Python desktop quand SIFT est dispo.
- ``"orb"``     fallback ORB + RANSAC quand SIFT n'est pas compile.

L'API publique reste identique a la version precedente :
``Aligner().align(images) -> List[np.ndarray]``.
"""
from __future__ import annotations

import logging
from typing import List, Tuple

import cv2
import numpy as np


class Aligner:
    """Aligne une liste d'images sur une image de reference centrale."""

    def __init__(
        self,
        detector: str = "phase",
        ratio_test: float = 0.75,
        ransac_thresh: float = 3.0,
    ):
        self.logger = logging.getLogger(__name__)
        self.ratio_test = ratio_test
        self.ransac_thresh = ransac_thresh
        self.detector_name = detector.lower()

        if self.detector_name == "sift" and hasattr(cv2, "SIFT_create"):
            self._features = cv2.SIFT_create()
        elif self.detector_name in ("sift", "orb"):
            self._features = cv2.ORB_create(nfeatures=4000)
            if self.detector_name == "sift":
                self.logger.warning("SIFT indisponible, fallback ORB.")
            self.detector_name = "orb"
        else:
            self._features = None  # mode phase

    def align(self, images: List[np.ndarray]) -> List[np.ndarray]:
        """Renvoie la liste des homographies H, H[ref_idx] = identite."""
        if len(images) < 2:
            raise ValueError("Au moins 2 images necessaires.")
        if self.detector_name == "phase":
            return self._align_phase(images)
        return self._align_features(images)

    # ------------------------------------------------------------------ #
    #  Alignement assisté par clics (similarité par moindres carrés)
    # ------------------------------------------------------------------ #
    @staticmethod
    def align_from_clicks(
        images: List[np.ndarray],
        pair_clicks: List[List[Tuple[Tuple[float, float], Tuple[float, float]]]],
        fallback_Hs: List[np.ndarray] = None,
    ) -> List[np.ndarray]:
        """
        Calcule une similarité (translation + rotation + échelle uniforme)
        entre chaque paire de photos consécutives à partir de points clicqués
        par l'utilisateur, puis chaîne les transformations vers l'image
        de référence centrale.

        Paramètres
        ----------
        images       : liste de N images (vignettes BGR).
        pair_clicks  : liste de N-1 éléments. ``pair_clicks[k]`` est une
                       liste de correspondances ``((ax, ay), (bx, by))``
                       où (ax, ay) est un point dans ``images[k]`` et
                       (bx, by) le même point physique dans ``images[k+1]``.
        fallback_Hs  : liste optionnelle de N homographies déjà connues
                       (issues d'un alignement précédent / auto). Pour les
                       paires sans clics suffisants, la transformation
                       relative ``rel[k+1] = inv(H[k]) @ H[k+1]`` est
                       reprise de ce fallback. Sans fallback, ces paires
                       reçoivent l'identité (= image placée au même endroit
                       que sa voisine, comportement historique).

        Retourne
        --------
        ``Hs``  liste de N matrices 3×3. ``Hs[ref_idx] = I``.
        """
        n = len(images)
        if n < 2:
            raise ValueError("Au moins 2 images necessaires.")
        if len(pair_clicks) != n - 1:
            raise ValueError(
                f"Il faut {n - 1} jeux de clics, reçu {len(pair_clicks)}."
            )

        ref_idx = n // 2

        # rel[i] aligne image i sur image i-1
        rel: List[np.ndarray] = [np.eye(3, dtype=np.float64) for _ in range(n)]

        # Dérive les rels existantes depuis fallback_Hs (si fourni)
        # rel[k+1] = inv(H[k]) @ H[k+1] : transformation pour passer de
        # l'image k+1 au repère de l'image k.
        fallback_rels: List[np.ndarray] = None
        if fallback_Hs is not None and len(fallback_Hs) == n:
            fallback_rels = [np.eye(3, dtype=np.float64) for _ in range(n)]
            for k in range(n - 1):
                try:
                    fallback_rels[k + 1] = (
                        np.linalg.inv(fallback_Hs[k]) @ fallback_Hs[k + 1]
                    )
                except np.linalg.LinAlgError:
                    pass  # garde l'identité par défaut

        for k in range(n - 1):  # paire (k, k+1)
            pts = pair_clicks[k]
            if len(pts) < 2:
                # Pas assez de points : préserve l'alignement existant si possible
                if fallback_rels is not None:
                    rel[k + 1] = fallback_rels[k + 1]
                continue
            pts_a = np.float32([p[0] for p in pts])   # dans image k
            pts_b = np.float32([p[1] for p in pts])   # dans image k+1

            # Vérification préalable : les points source doivent avoir un écart
            # suffisant pour que la similarité soit déterminée (évite les NaN).
            spread_b = float(np.max(np.linalg.norm(pts_b - pts_b.mean(axis=0), axis=1)))
            spread_a = float(np.max(np.linalg.norm(pts_a - pts_a.mean(axis=0), axis=1)))
            if spread_b < 1.0 or spread_a < 1.0:
                raise RuntimeError(
                    f"Paire {k + 1} : les points cliqués sont trop proches les uns des"
                    " autres (spread < 1 px). Cliquez sur des points bien espacés dans"
                    " chaque image."
                )

            # On veut M tel que pts_a = M @ pts_b  (image k+1 mappée sur image k)
            M, _inliers = cv2.estimateAffinePartial2D(
                pts_b, pts_a,
                method=cv2.RANSAC,
                ransacReprojThreshold=5.0,
                maxIters=2000,
                refineIters=10,
            )

            # estimateAffinePartial2D peut renvoyer None ou une matrice avec NaN
            # sur des configurations dégénérées (points colinéaires, etc.)
            if M is None or np.any(np.isnan(M)):
                raise RuntimeError(
                    f"Paire {k + 1} : impossible de calculer la transformation"
                    " (points trop peu discriminants). Ajoutez des correspondances"
                    " mieux réparties dans l'image."
                )

            rel[k + 1] = np.vstack([M, [0.0, 0.0, 1.0]]).astype(np.float64)

        # Chaînage vers la référence
        Hs: List[np.ndarray] = [np.eye(3, dtype=np.float64) for _ in range(n)]
        for i in range(ref_idx + 1, n):
            Hs[i] = Hs[i - 1] @ rel[i]
        for i in range(ref_idx - 1, -1, -1):
            Hs[i] = Hs[i + 1] @ np.linalg.inv(rel[i + 1])

        return Hs

    # --- mode phase ---------------------------------------------------- #
    def _align_phase(self, images: List[np.ndarray]) -> List[np.ndarray]:
        n = len(images)
        ref_idx = n // 2

        rel: List[np.ndarray] = [np.eye(3, dtype=np.float64) for _ in range(n)]
        for i in range(1, n):
            tx, ty = self._phase_pair_translation(images[i - 1], images[i])
            self.logger.debug("phase pair %d->%d : tx=%.2f ty=%.2f", i, i - 1, tx, ty)
            rel[i] = np.array(
                [[1.0, 0.0, tx], [0.0, 1.0, ty], [0.0, 0.0, 1.0]],
                dtype=np.float64,
            )

        Hs: List[np.ndarray] = [np.eye(3, dtype=np.float64) for _ in range(n)]
        for i in range(ref_idx + 1, n):
            Hs[i] = Hs[i - 1] @ rel[i]
        for i in range(ref_idx - 1, -1, -1):
            Hs[i] = Hs[i + 1] @ np.linalg.inv(rel[i + 1])

        return Hs

    @staticmethod
    def _phase_pair_translation(a: np.ndarray, b: np.ndarray) -> Tuple[float, float]:
        ga = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
        gb = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32)

        H = max(ga.shape[0], gb.shape[0])
        W = max(ga.shape[1], gb.shape[1])

        canv_a = np.zeros((H, W), dtype=np.float32)
        canv_b = np.zeros((H, W), dtype=np.float32)
        canv_a[: ga.shape[0], : ga.shape[1]] = ga
        canv_b[: gb.shape[0], : gb.shape[1]] = gb

        hann = cv2.createHanningWindow((W, H), cv2.CV_32F)
        try:
            (dx, dy), response = cv2.phaseCorrelate(canv_a, canv_b, hann)
        except cv2.error:
            return 0.0, 0.0

        if response < 0.01:
            return 0.0, 0.0

        return float(-dx), float(-dy)

    # --- mode features ------------------------------------------------- #
    def _align_features(self, images: List[np.ndarray]) -> List[np.ndarray]:
        ref_idx = len(images) // 2
        Hs: List[np.ndarray | None] = [None] * len(images)
        Hs[ref_idx] = np.eye(3, dtype=np.float64)

        feats = [self._features.detectAndCompute(img, None) for img in images]

        if self.detector_name == "sift":
            matcher = cv2.BFMatcher(cv2.NORM_L2)
        else:
            matcher = cv2.BFMatcher(cv2.NORM_HAMMING)

        for i, _img in enumerate(images):
            if i == ref_idx:
                continue
            kp_i, des_i = feats[i]
            kp_r, des_r = feats[ref_idx]
            if des_i is None or des_r is None:
                raise RuntimeError(f"Aucun descripteur pour image {i}")

            raw = matcher.knnMatch(des_i, des_r, k=2)
            good = [m for m, n in raw if m.distance < self.ratio_test * n.distance]
            self.logger.debug("matches %d->%d : %d", i, ref_idx, len(good))

            if len(good) < 6:
                raise RuntimeError(f"Matching insuffisant entre images {i} et {ref_idx}")

            pts_i = np.float32([kp_i[m.queryIdx].pt for m in good])
            pts_r = np.float32([kp_r[m.trainIdx].pt for m in good])

            H, _mask = cv2.findHomography(pts_i, pts_r, cv2.RANSAC, self.ransac_thresh)
            if H is None:
                raise RuntimeError(f"Homographie impossible entre {i} et {ref_idx}")
            Hs[i] = H

        return [H if H is not None else np.eye(3, dtype=np.float64) for H in Hs]
