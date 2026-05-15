import numpy as np
import cv2

from pcbmosaic.core.stitcher import Stitcher

def _synthetic_tile(offset_x: int, offset_y: int, size=400, bg=180):
    """Tuile synthétique avec un fond gris uni et un cercle coloré.

    Le fond gris garantit que les pixels non-noirs couvrent toute l'image,
    indépendamment de la forme des cercles. Cela permet de vérifier que le
    stitcher remplit bien le canvas sans zones noires indésirables.
    """
    img = np.full((size, size, 3), bg, np.uint8)
    cv2.circle(
        img, (size // 2 + offset_x, size // 2 + offset_y), size // 3, (0, 200, 0), -1
    )
    return img


def test_stitcher_layer_order_first_wins():
    """L'ordre de la liste = ordre des couches. images[0] doit dominer
    dans les zones de recouvrement, peu importe l'index de la 'référence'."""
    # 2 tuiles 200x200 strictement superposées, l'une rouge, l'autre bleue
    red  = np.zeros((200, 200, 3), np.uint8)
    red[:, :] = (0, 0, 255)        # BGR : rouge
    blue = np.zeros((200, 200, 3), np.uint8)
    blue[:, :] = (255, 0, 0)       # BGR : bleu

    Hs = [np.eye(3, dtype=np.float64), np.eye(3, dtype=np.float64)]

    # Cas 1 : rouge en haut de la liste → résultat doit être rouge
    out_red_top = Stitcher().stitch([red, blue], Hs)
    center = out_red_top[100, 100]
    assert tuple(center) == (0, 0, 255), f"attendu rouge, obtenu {tuple(center)}"

    # Cas 2 : bleu en haut de la liste → résultat doit être bleu
    out_blue_top = Stitcher().stitch([blue, red], Hs)
    center = out_blue_top[100, 100]
    assert tuple(center) == (255, 0, 0), f"attendu bleu, obtenu {tuple(center)}"


def test_stitcher_minimal():
    """4 tuiles avec fond gris, homographies identité → canvas entièrement rempli."""
    imgs = [
        _synthetic_tile(0, 0),
        _synthetic_tile(-80, 0),
        _synthetic_tile(0, -80),
        _synthetic_tile(-80, -80),
    ]
    Hs = [np.eye(3, dtype=np.float64) for _ in imgs]  # déjà alignées
    out = Stitcher(blend_mode="average").stitch(imgs, Hs)
    h, w = out.shape[:2]
    # Dimensions minimales attendues
    assert w >= 400 and h >= 400
    # Avec un fond gris (valeur 180), tous les pixels du canvas doivent être
    # non-noirs : on tolère < 1 % de pixels noirs (bords warpPerspective).
    nz = cv2.countNonZero(cv2.cvtColor(out, cv2.COLOR_BGR2GRAY))
    assert nz > 0.99 * w * h, f"Trop de pixels noirs : {nz}/{w * h} ({100 * nz / (w * h):.1f}%)"
