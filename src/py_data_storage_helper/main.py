import sys
import argparse
from PySide6.QtWidgets import QApplication

if __package__ is None or __package__ == "":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from py_data_storage_helper.constants import APP_NAME
    from py_data_storage_helper.ui.theme import apply_theme
    from py_data_storage_helper.ui.main_window import MainWindow
else:
    from .constants import APP_NAME
    from .ui.theme import apply_theme
    from .ui.main_window import MainWindow


def main() -> None:
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument("--load-plan", type=str, help="Pfad zu einer .stplan Datei")
    args, _ = parser.parse_known_args()

    app = QApplication(sys.argv)
    apply_theme(app)

    window = MainWindow(initial_plan_path=args.load_plan)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
