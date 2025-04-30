# setup.py
from setuptools import setup, find_packages

setup(
    name="pcb-mosaic-maker",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "PySide6>=6.7",
        "numpy",
        "opencv-python",
        "Pillow",
        "scikit-image",
        "tqdm",
    ],
    entry_points={
        "console_scripts": [
            "pcb-mosaic-maker=pcbmosaic.gui.main_window:main",
        ],
    },
)
