"""
Tests unitaires pour Aligner.align_from_clicks.

On vérifie que :
- la translation pure est retrouvée (3 paires, 2 images)
- la translation + chaînage fonctionnent sur 3 images
- la rotation+échelle sont correctement estimées
- les cas dégénérés (points confondus) lèvent une RuntimeError
"""
import numpy as np
import pytest

from pcbmosaic.core.aligner import Aligner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_pair(pts_a, pts_b):
    """Construit une liste de correspondances ((ax,ay),(bx,by))."""
    return [((float(ax), float(ay)), (float(bx), float(by)))
            for (ax, ay), (bx, by) in zip(pts_a, pts_b)]


# ---------------------------------------------------------------------------
def test_click_align_pure_translation_2_images():
    """2 photos, décalage horizontal de 60 px vers la droite."""
    # Image 0 : feature visible à (150, 90), (150, 200), (200, 150)
    # Image 1 (ref) : mêmes features à (90, 90), (90, 200), (140, 150)
    pts0 = [(150, 90), (150, 200), (200, 150)]
    pts1 = [(90,  90), (90,  200), (140, 150)]

    pair_clicks = [_make_pair(pts0, pts1)]   # une seule paire (0→1)

    imgs = [np.zeros((320, 240, 3), np.uint8)] * 2
    Hs = Aligner.align_from_clicks(imgs, pair_clicks)

    assert len(Hs) == 2
    # Image 1 est la référence (n//2 = 1)
    assert np.allclose(Hs[1], np.eye(3), atol=1e-6)
    # Image 0 doit être décalée de +60 en x pour atterrir sur image 1
    # Feature (150,90) → doit mapper en (90,90) dans le repère de référence
    mapped = Hs[0] @ np.array([150.0, 90.0, 1.0])
    assert np.allclose(mapped[:2], [90.0, 90.0], atol=0.5)


def test_click_align_chain_3_images():
    """3 photos : a—60px—b (ref)—40px—c, chaînage doit être cohérent."""
    # Paire (a, b) : même feature à (150,90) dans a, (90,90) dans b
    pts_a_in_a = [(150, 90), (150, 200), (80, 150)]
    pts_a_in_b = [(90,  90), (90,  200), (20, 150)]

    # Paire (b, c) : même feature à (90,90) dans b, (50,90) dans c
    pts_b_in_b = [(90,  90), (90,  200), (20, 150)]
    pts_b_in_c = [(50,  90), (50,  200), (-20, 150)]  # décalage de 40 px à gauche

    pair_clicks = [
        _make_pair(pts_a_in_a, pts_a_in_b),
        _make_pair(pts_b_in_b, pts_b_in_c),
    ]

    imgs = [np.zeros((320, 240, 3), np.uint8)] * 3
    Hs = Aligner.align_from_clicks(imgs, pair_clicks)

    # Référence = image 1
    assert np.allclose(Hs[1], np.eye(3), atol=1e-6)

    # Feature de l'image 0 doit atterrir en (90,90)
    mapped_0 = Hs[0] @ np.array([150.0, 90.0, 1.0])
    assert np.allclose(mapped_0[:2], [90.0, 90.0], atol=0.5)

    # Feature de l'image 2 doit atterrir en (90,90)
    mapped_2 = Hs[2] @ np.array([50.0, 90.0, 1.0])
    assert np.allclose(mapped_2[:2], [90.0, 90.0], atol=0.5)


def test_click_align_rotation_and_scale():
    """2 photos : image 1 est image 0 avec rotation 15° + scale 1.1 autour du centre."""
    W, H = 320, 240
    cx, cy = W / 2.0, H / 2.0
    theta = np.radians(15)
    scale = 1.1
    cos_t, sin_t = np.cos(theta), np.sin(theta)

    def transform(px, py):
        """Applique rotation+échelle autour du centre."""
        dx, dy = px - cx, py - cy
        x1 = cx + scale * (cos_t * dx - sin_t * dy)
        y1 = cy + scale * (sin_t * dx + cos_t * dy)
        return x1, y1

    # 4 points bien répartis dans l'image
    src_pts = [(80, 60), (240, 60), (80, 180), (240, 180)]
    dst_pts = [transform(px, py) for px, py in src_pts]

    pair_clicks = [_make_pair(src_pts, dst_pts)]
    imgs = [np.zeros((H, W, 3), np.uint8)] * 2
    Hs = Aligner.align_from_clicks(imgs, pair_clicks)

    # Vérifie que chaque point source est mappé vers le bon endroit
    for (sx, sy), (dx, dy) in zip(src_pts, dst_pts):
        mapped = Hs[0] @ np.array([sx, sy, 1.0])
        assert np.allclose(mapped[:2], [dx, dy], atol=1.0), \
            f"({sx},{sy}) -> {mapped[:2]}, attendu ({dx:.1f},{dy:.1f})"


def test_click_align_fallback_Hs_preserves_alignment():
    """Quand une paire n'a pas de clics, fallback_Hs doit préserver l'alignement
    courant de cette paire (au lieu de retomber sur l'identité)."""
    # 3 photos. L'utilisateur a cliqué sur la paire (0,1) mais pas (1,2).
    # Hs existants (auto-align par exemple) : photo 0 décalée de -60 px,
    # photo 2 décalée de +40 px par rapport à la ref (photo 1).
    existing_Hs = [
        np.array([[1, 0, -60], [0, 1, 0], [0, 0, 1]], float),  # H[0]
        np.eye(3),                                              # H[1] = ref
        np.array([[1, 0, 40], [0, 1, 0], [0, 0, 1]], float),   # H[2]
    ]

    # L'utilisateur reclique la paire (0,1) — disons 50 px à gauche au lieu de 60
    pair_clicks = [
        _make_pair(
            [(150, 90), (150, 200), (200, 150)],
            [(100, 90), (100, 200), (150, 150)],  # tx = -50
        ),
        [],  # paire (1,2) : aucun clic → doit être préservée
    ]

    imgs = [np.zeros((300, 300, 3), np.uint8)] * 3
    Hs = Aligner.align_from_clicks(imgs, pair_clicks, fallback_Hs=existing_Hs)

    # Hs[1] reste l'identité (référence)
    assert np.allclose(Hs[1], np.eye(3), atol=1e-6)
    # Hs[0] reflète les nouveaux clics : tx = -50
    assert abs(Hs[0][0, 2] - (-50)) < 0.5
    # Hs[2] doit avoir été préservé via fallback (rel de (1,2) inchangée)
    assert abs(Hs[2][0, 2] - 40) < 0.5


def test_click_align_no_fallback_falls_back_to_identity():
    """Sans fallback_Hs, une paire vide retombe sur l'identité (comportement historique)."""
    pair_clicks = [
        _make_pair(
            [(150, 90), (150, 200), (200, 150)],
            [(100, 90), (100, 200), (150, 150)],
        ),
        [],  # vide, pas de fallback
    ]
    imgs = [np.zeros((300, 300, 3), np.uint8)] * 3
    Hs = Aligner.align_from_clicks(imgs, pair_clicks, fallback_Hs=None)

    # Hs[2] doit être identité car rel[2] = I sans fallback
    # (Hs[1] est aussi identité car c'est la ref)
    assert np.allclose(Hs[2], np.eye(3), atol=1e-6)


def test_click_align_degenerate_raises():
    """Points identiques dans une image → doit lever RuntimeError."""
    # Tous les points source (pts_b) au même endroit → spread < 1px
    pair_clicks = [
        [
            ((100.0, 80.0), (150.0, 90.0)),
            ((120.0, 90.0), (150.0, 90.0)),   # pts_b tous en (150,90)
            ((80.0,  70.0), (150.0, 90.0)),
        ]
    ]
    imgs = [np.zeros((200, 200, 3), np.uint8)] * 2
    with pytest.raises(RuntimeError, match="Paire 1"):
        Aligner.align_from_clicks(imgs, pair_clicks)
