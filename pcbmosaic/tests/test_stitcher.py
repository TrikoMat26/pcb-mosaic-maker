import numpy as np
import cv2

from pcbmosaic.core.stitcher import Stitcher

def _synthetic_tile(offset_x: int, offset_y: int, size=400):
    img = np.zeros((size, size, 3), np.uint8)
    cv2.circle(
        img, (size // 2 + offset_x, size // 2 + offset_y), size // 3, (0, 255, 0), -1
    )
    return img

def test_stitcher_minimal():
    imgs = [
        _synthetic_tile(0, 0),
        _synthetic_tile(-80, 0),
        _synthetic_tile(0, -80),
        _synthetic_tile(-80, -80),
    ]
    Hs = [np.eye(3, dtype=np.float64) for _ in imgs]  # déjà alignées
    out = Stitcher(blend_mode="average").stitch(imgs, Hs)
    h, w = out.shape[:2]
    # Largeur attendue : ~ size + |offset_x|
    assert w >= 400 and h >= 400
    # Pas plus de 1 % de pixels noirs
    nz = cv2.countNonZero(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY))
    assert nz > 0.99 * w * h
