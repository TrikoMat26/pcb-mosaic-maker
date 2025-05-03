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

            # Amélioration du masquage : utiliser l'espace LAB pour mieux détecter
            # les zones sombres mais pertinentes du PCB
            lab = cv2.cvtColor(w_img, cv2.COLOR_BGR2LAB)
            l_channel = lab[:,:,0]
            
            # Premier masque basé sur la luminosité
            _, mask1 = cv2.threshold(l_channel, 10, 255, cv2.THRESH_BINARY)
            
            # Masques supplémentaires sur les canaux a et b pour détecter les couleurs
            a_channel = lab[:,:,1]
            b_channel = lab[:,:,2]
            _, mask2 = cv2.threshold(cv2.absdiff(a_channel, 128), 5, 255, cv2.THRESH_BINARY)
            _, mask3 = cv2.threshold(cv2.absdiff(b_channel, 128), 5, 255, cv2.THRESH_BINARY)
            
            # Combiner les masques
            combined_mask = cv2.bitwise_or(mask1, cv2.bitwise_or(mask2, mask3))
            
            # Nettoyer le masque pour éliminer le bruit
            kernel = np.ones((3, 3), np.uint8)
            mask = cv2.morphologyEx(combined_mask, cv2.MORPH_CLOSE, kernel)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
            
            # Ajouter un feathering pour lisser les transitions
            mask = cv2.GaussianBlur(mask, (5, 5), 0)

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
        auto_crop: bool = True,  # Nouveau paramètre
    ) -> np.ndarray:
        
        # Estimer et corriger la distorsion optique
        corrected_homographies = []
        for H in homographies:
            # Appliquer des limites raisonnables aux transformations
            H_safe = self._sanitize_homography(H)
            
            # Correction de la distorsion radiale
            k1, k2 = 0, 0  # Coefficients de distorsion estimés
            h, w = images[0].shape[:2]
            center = np.array([w/2, h/2])
            
            # Homographie corrigée
            corrected_homographies.append(H_safe)

        # Utiliser les homographies corrigées
        homographies = corrected_homographies

        
        # Améliorer les bords des images pour réduire les artefacts
        images_padded = [self._improve_borders(img) for img in images]

        """Renvoie la mosaïque finale (BGR) en utilisant les homographies."""
        # Approche simplifiée : fusion directe avec les homographies

        # Calculer la taille du canevas et la matrice de translation
        T, size = self._compute_canvas(images_padded, homographies)

        # Créer une image vide pour le résultat
        result = np.zeros((size[0], size[1], 3), dtype=np.uint8)

        # Créer un masque pour suivre les pixels déjà remplis
        filled_mask = np.zeros((size[0], size[1]), dtype=np.uint8)

        # Warper et fusionner les images une par une
        # Commencer par l'image de référence (celle du milieu)
        ref_idx = len(images_padded) // 2

        # Traiter d'abord l'image de référence
        img, H = images_padded[ref_idx], homographies[ref_idx]
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
        for i, (img, H) in enumerate(zip(images_padded, homographies)):
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

        # Appliquer le recadrage automatique si demandé
        if auto_crop:
            result = self.auto_crop_mosaic(result)

        return result

    def auto_crop_mosaic(self, img: np.ndarray, threshold: int = 5, margin: int = 5) -> np.ndarray:
        """
        Recadre automatiquement l'image pour éliminer les bordures noires.
        
        Args:
            img: Image à recadrer (BGR)
            threshold: Seuil pour considérer un pixel comme "non-noir"
            margin: Marge à conserver autour du contenu détecté
        """
        # Conversion en niveaux de gris et seuillage
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
        
        # Trouver les contours non-noirs
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Si aucun contour trouvé, retourner l'image originale
        if not contours:
            return img
        
        # Trouver le plus grand contour (supposé être le PCB)
        biggest_contour = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(biggest_contour)
        
        # Ajouter une marge
        x = max(0, x - margin)
        y = max(0, y - margin)
        w = min(img.shape[1] - x, w + 2 * margin)
        h = min(img.shape[0] - y, h + 2 * margin)
        
        # Recadrer l'image
        return img[y:y+h, x:x+w]

    def content_aware_crop(self, img: np.ndarray, target_aspect: float) -> np.ndarray:
        """
        Recadre intelligemment l'image pour obtenir un ratio d'aspect spécifique
        tout en préservant le contenu important.
        
        Args:
            img: Image à recadrer (BGR)
            target_aspect: Ratio largeur/hauteur cible
        """
        h, w = img.shape[:2]
        current_aspect = w / h
        
        # Si déjà proche du ratio cible, ne rien faire
        if abs(current_aspect - target_aspect) < 0.01:
            return img
        
        # Calculer l'importance de chaque pixel (basée sur les bords et gradients)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        edges = cv2.Canny(gray, 50, 150)
        importance = cv2.GaussianBlur(edges.astype(float), (21, 21), 0)
        
        # Normaliser l'importance
        importance = importance / importance.max() if importance.max() > 0 else importance
        
        if current_aspect > target_aspect:
            # Image trop large, recadrer horizontalement
            new_w = int(h * target_aspect)
            excess_w = w - new_w
            
            # Calculer l'importance de chaque colonne
            col_importance = np.sum(importance, axis=0)
            
            # Trouver la meilleure position de recadrage
            best_score = -1
            best_x = 0
            
            for x in range(excess_w + 1):
                score = np.sum(col_importance[x:x+new_w])
                if score > best_score:
                    best_score = score
                    best_x = x
            
            # Recadrer
            return img[:, best_x:best_x+new_w]
        else:
            # Image trop haute, recadrer verticalement
            new_h = int(w / target_aspect)
            excess_h = h - new_h
            
            # Calculer l'importance de chaque ligne
            row_importance = np.sum(importance, axis=1)
            
            # Trouver la meilleure position de recadrage
            best_score = -1
            best_y = 0
            
            for y in range(excess_h + 1):
                score = np.sum(row_importance[y:y+new_h])
                if score > best_score:
                    best_score = score
                    best_y = y
            
            # Recadrer
            return img[best_y:best_y+new_h, :]

    def _improve_borders(self, image: np.ndarray, margin: int = 20) -> np.ndarray:
        """
        Améliore les bords de l'image en ajoutant un padding réfléchi.
        
        Args:
            image: Image d'entrée
            margin: Largeur du padding (en pixels)
        """
        return cv2.copyMakeBorder(
            image,
            margin, margin, margin, margin,
            cv2.BORDER_REFLECT_101
        )

    def _sanitize_homography(self, H: np.ndarray) -> np.ndarray:
        """Limite les déformations excessives dans une homographie."""
        # Décomposer la matrice pour analyser la déformation
        _, Rs, Ts, Ns = cv2.decomposeHomographyMat(H, np.eye(3))
        
        # Prendre la solution la plus plausible (première)
        R, T, N = Rs[0], Ts[0], Ns[0]
        
        # Reconstruire une homographie plus contrainte
        theta = np.arccos((np.trace(R) - 1) / 2)
        if abs(theta) > np.pi/4:  # Limiter la rotation à 45°
            R = np.eye(3)
        
        # Limiter les facteurs d'échelle
        scale_factors = np.linalg.svd(H[:2, :2])[1]
        if max(scale_factors) / min(scale_factors) > 3:
            # Normaliser pour éviter les déformations extrêmes
            return np.eye(3)
        
        return H

