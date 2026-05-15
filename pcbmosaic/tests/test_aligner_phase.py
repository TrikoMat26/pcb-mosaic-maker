"""Vérifie que l'aligneur en mode phase retrouve une translation connue."""
import numpy as np
import cv2

from pcbmosaic.core.aligner import Aligner


def _texture(seed: int = 7, size: int = 320) -> np.ndarray:
    """Crée un patch synthétique riche en features (bruit basse fréquence + cercles)."""
    rng = np.random.default_rng(seed)
    img = (rng.random((size, size, 3)) * 200 + 30).astype(np.uint8)
    img = cv2.GaussianBlur(img, (15, 15), 5)
    cv2.circle(img, (80, 80), 25, (255, 0, 0), -1)
    cv2.circle(img, (220, 150), 35, (0, 255, 0), -1)
    cv2.rectangle(img, (60, 200), (150, 280), (0, 0, 255), -1)
    return img


def test_phase_alignment_recovers_translation():
    full = _texture()
    h, w = full.shape[:2]
    # Trois "vues" se chevauchant horizontalement
    a = full[:, :220]
    b = full[:, 60:280]
    c = full[:, 100:]
    aligner = Aligner(detector="phase")
    Hs = aligner.align([a, b, c])

    # On vérifie que les translations sont du bon ordre (à 5 px près)
    assert Hs[0].shape == (3, 3)
    assert Hs[1].shape == (3, 3)
    assert Hs[2].shape == (3, 3)

    # H[ref_idx] (index 1 ici) doit être l'identité
    assert np.allclose(Hs[1], np.eye(3), atol=1e-9)

    # H[0] doit translater à gauche (tx négatif), H[2] à droite (tx positif)
    tx0, tx2 = Hs[0][0, 2], Hs[2][0, 2]
    assert tx0 < -20, f"image 0 doit être à gauche : tx={tx0}"
    assert tx2 > 20,  f"image 2 doit être à droite : tx={tx2}"
