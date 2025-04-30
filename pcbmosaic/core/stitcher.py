from __future__ import annotations
from typing import List, Literal, Tuple

import cv2
import numpy as np
from skimage.transform import pyramid_gaussian, pyramid_laplacian, resize


class Stitcher:
    """Warpe et fusionne plusieurs images grâce à leurs homographies."""

    def __init__(
        self,
        blend_mode: Literal["multiband", "average"] = "multiband",
        num_levels: int = 5,
    ):
        self.blend_mode = blend_mode
        self.num_levels = num_levels

    # ------------------------------------------------------------------ #
    @staticmethod
    def _compute_canvas(
        images: List[np.ndarray], Hs: List[np.ndarray]
    ) -> Tuple[np.ndarray, Tuple[int, int]]:
        """Retourne la matrice de translation & taille canevas."""
        corners = []
        for img, H in zip(images, Hs):
            h, w = img.shape[:2]
            pts = np.array([[0, 0], [0, h], [w, h], [w, 0]], dtype=np.float32)
            pts = cv2.perspectiveTransform(pts[None, :, :], H)[0]
            corners.append(pts)

        all_pts = np.vstack(corners)
        xmin, ymin = np.floor(all_pts.min(axis=0)).astype(int)
        xmax, ymax = np.ceil(all_pts.max(axis=0)).astype(int)

        tx, ty = -xmin, -ymin
        canvas_size = (int(ymax - ymin), int(xmax - xmin))  # (h, w)
        T = np.array([[1, 0, tx], [0, 1, ty], [0, 0, 1]], dtype=np.float64)
        return T, canvas_size

    # ------------------------------------------------------------------ #
    def _warp_images(
        self, images: List[np.ndarray], Hs: List[np.ndarray], T: np.ndarray, size: Tuple
    ):
        warped, masks = [], []
        for img, H in zip(images, Hs):
            # Appliquer la transformation homographique
            Ht = T @ H

            # Utiliser une interpolation cubique pour une meilleure qualité
            w_img = cv2.warpPerspective(
                img,
                Ht,
                (size[1], size[0]),
                flags=cv2.INTER_CUBIC,
                borderMode=cv2.BORDER_CONSTANT
            )

            # Créer un masque précis pour les pixels valides
            # Utiliser un seuil plus élevé pour éviter les pixels sombres aux bords
            gray = cv2.cvtColor(w_img, cv2.COLOR_BGR2GRAY)
            _, mask = cv2.threshold(gray, 5, 255, cv2.THRESH_BINARY)

            # Appliquer une érosion suivie d'une dilatation pour éliminer le bruit
            kernel = np.ones((3, 3), np.uint8)
            mask = cv2.erode(mask, kernel, iterations=1)
            mask = cv2.dilate(mask, kernel, iterations=2)

            warped.append(w_img)
            masks.append(mask.astype(bool))
        return warped, masks

    # ------------------------------------------------------------------ #
    def _multiband_blend(
        self, imgs: List[np.ndarray], masks: List[np.ndarray]
    ) -> np.ndarray:
        laplacians = [
            list(pyramid_laplacian(img / 255.0, max_layer=self.num_levels))
            for img in imgs
        ]
        gaussians = [
            list(pyramid_gaussian(mask.astype(float), max_layer=self.num_levels))
            for mask in masks
        ]

        blended_pyr = []
        for level in range(self.num_levels + 1):
            num = sum(
                g[level][:, :, None] * l[level] for g, l in zip(gaussians, laplacians)
            )
            denom = sum(g[level][:, :, None] for g in gaussians) + 1e-8
            blended_pyr.append(num / denom)

        # Reconstruction
        blended = blended_pyr[-1]
        for lvl in range(self.num_levels - 1, -1, -1):
            blended = resize(blended, blended_pyr[lvl].shape, order=1)
            blended += blended_pyr[lvl]
        blended = np.clip(blended * 255, 0, 255).astype(np.uint8)
        return blended

    # ------------------------------------------------------------------ #
    def stitch(
        self,
        images: List[np.ndarray],
        homographies: List[np.ndarray],
        scale: float = 1.0,
    ) -> np.ndarray:
        """Renvoie la mosaïque finale (BGR) en utilisant les homographies."""
        # Approche simplifiée : fusion directe avec les homographies

        # Calculer la taille du canevas et la matrice de translation
        T, size = self._compute_canvas(images, homographies)

        # Créer une image vide pour le résultat
        result = np.zeros((size[0], size[1], 3), dtype=np.uint8)

        # Créer un masque pour suivre les pixels déjà remplis
        filled_mask = np.zeros((size[0], size[1]), dtype=np.uint8)

        # Warper et fusionner les images une par une
        # Commencer par l'image de référence (celle du milieu)
        ref_idx = len(images) // 2

        # Traiter d'abord l'image de référence
        img, H = images[ref_idx], homographies[ref_idx]
        Ht = T @ H
        warped = cv2.warpPerspective(
            img, Ht, (size[1], size[0]),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT
        )

        # Créer un masque pour les pixels non noirs
        gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 1, 255, cv2.THRESH_BINARY)

        # Copier l'image de référence dans le résultat
        result = cv2.bitwise_and(warped, warped, mask=mask)
        filled_mask = mask.copy()

        # Traiter les autres images
        for i, (img, H) in enumerate(zip(images, homographies)):
            if i == ref_idx:
                continue  # Déjà traité

            # Appliquer l'homographie
            Ht = T @ H
            warped = cv2.warpPerspective(
                img, Ht, (size[1], size[0]),
                flags=cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_CONSTANT
            )

            # Créer un masque pour les pixels non noirs
            gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
            _, mask = cv2.threshold(gray, 1, 255, cv2.THRESH_BINARY)

            # Ne copier que les pixels qui ne sont pas déjà remplis
            new_pixels = cv2.bitwise_and(mask, cv2.bitwise_not(filled_mask))

            # Fusionner avec le résultat actuel
            result = cv2.bitwise_or(
                cv2.bitwise_and(warped, warped, mask=new_pixels),
                result
            )

            # Mettre à jour le masque des pixels remplis
            filled_mask = cv2.bitwise_or(filled_mask, mask)

        # Redimensionner si nécessaire
        if not np.isclose(scale, 1.0):
            h, w = result.shape[:2]
            result = cv2.resize(result, (int(w * scale), int(h * scale)))

        return result
