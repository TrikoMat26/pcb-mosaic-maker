"""Point d'entrée unique pour PyInstaller et le lancement direct."""
import sys
import traceback
from pathlib import Path

from pcbmosaic.gui.main_window import main


_LOG_PATH = Path(__file__).resolve().parent / "pcbmosaic-error.log"


def _install_exception_logger():
    """Toute exception non gérée est aussi écrite dans pcbmosaic-error.log.

    Indispensable quand on lance le .exe PyInstaller sans console : sinon
    le programme se ferme sans laisser de trace de l'erreur.
    """
    default_hook = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        try:
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write("=" * 70 + "\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
                f.write("\n")
        except Exception:
            pass
        default_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook


if __name__ == "__main__":
    _install_exception_logger()
    main()
