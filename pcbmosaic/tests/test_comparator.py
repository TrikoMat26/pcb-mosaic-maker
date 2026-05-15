"""Le comparateur doit détecter un défaut volontairement injecté."""
import numpy as np
import cv2

from pcbmosaic.core.comparator import Comparator


def _make_pcb_like(seed: int = 0, size: int = 480) -> np.ndarray:
    """PCB synthétique : fond vert sombre + pistes claires + composants noirs."""
    rng = np.random.default_rng(seed)
    img = np.full((size, size, 3), (40, 80, 30), dtype=np.uint8)  # vert PCB
    # Pistes verticales / horizontales
    for _ in range(8):
        x = rng.integers(20, size - 20)
        cv2.line(img, (x, 10), (x, size - 10), (160, 200, 100), 3)
    for _ in range(8):
        y = rng.integers(20, size - 20)
        cv2.line(img, (10, y), (size - 10, y), (160, 200, 100), 3)
    # Composants noirs (paquets carrés)
    for _ in range(12):
        x = rng.integers(20, size - 60)
        y = rng.integers(20, size - 60)
        cv2.rectangle(img, (x, y), (x + 35, y + 25), (15, 15, 15), -1)
    # Légère texture pour aider l'ECC
    noise = rng.integers(-8, 8, img.shape, dtype=np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    return img


def test_comparator_finds_injected_defect():
    ref = _make_pcb_like(seed=42)
    inspected = ref.copy()

    # On efface (avec la couleur du fond) une zone qui correspondait à
    # un composant : c'est un "composant manquant".
    cv2.rectangle(inspected, (200, 200), (260, 230), (40, 80, 30), -1)
    # Et on en ajoute un nouveau ailleurs (composant en trop)
    cv2.rectangle(inspected, (100, 380), (140, 410), (15, 15, 15), -1)

    cmp_ = Comparator(min_defect_area=80)
    res = cmp_.compare(ref, inspected)

    assert res.defect_mask.shape == ref.shape[:2]
    assert len(res.defects) >= 2, f"attendu au moins 2 défauts, eu {len(res.defects)}"

    # Les défauts doivent être triés par sévérité décroissante
    sevs = [d.severity for d in res.defects]
    assert sevs == sorted(sevs, reverse=True)

    # Chaque défaut doit avoir un id, une bbox et une centroid valides
    for d in res.defects:
        x, y, w, h = d.bbox
        assert w > 0 and h > 0
        assert 0 <= d.centroid[0] < ref.shape[1]
        assert 0 <= d.centroid[1] < ref.shape[0]
        assert 0.0 <= d.severity <= 1.0


def test_render_overlay_does_not_alter_reference():
    ref = _make_pcb_like(seed=7)
    inspected = ref.copy()
    cv2.rectangle(inspected, (50, 50), (90, 90), (250, 250, 250), -1)

    cmp_ = Comparator(min_defect_area=50)
    res = cmp_.compare(ref, inspected)
    overlay = Comparator.render_overlay(ref, res)

    # Tailles identiques
    assert overlay.shape == ref.shape
    # La référence n'a pas été modifiée par la fonction de rendu
    assert ref[0, 0, 0] == _make_pcb_like(seed=7)[0, 0, 0]
