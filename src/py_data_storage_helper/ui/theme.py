from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication

DARK_STYLESHEET = """
QMainWindow { background-color: #0f172a; color: #f8fafc; }
QWidget { font-family: 'Segoe UI', system-ui, sans-serif; color: #f8fafc; font-size: 13px; }
#SidebarFrame { background-color: #1e293b; border-right: 1px solid #334155; }
QPushButton.nav-btn { background-color: transparent; color: #94a3b8; text-align: left; padding: 10px 14px; border-radius: 8px; font-size: 13px; border: none; }
QPushButton.nav-btn:hover { background-color: #334155; color: #f8fafc; }
QPushButton.nav-btn:checked { background-color: #2563eb; color: #ffffff; font-weight: 600; }
QPushButton.action-primary { background-color: #2563eb; color: #ffffff; font-weight: 600; border-radius: 6px; padding: 8px 16px; border: none; }
QPushButton.action-primary:hover { background-color: #1d4ed8; }
QPushButton.action-secondary { background-color: #334155; color: #f8fafc; font-weight: 500; border-radius: 6px; padding: 8px 14px; border: 1px solid #475569; }
QPushButton.action-secondary:hover { background-color: #475569; }
QPushButton.action-danger { background-color: #ef4444; color: #ffffff; font-weight: 600; border-radius: 6px; padding: 8px 14px; border: none; }
QPushButton.action-danger:hover { background-color: #dc2626; }
QLineEdit, QComboBox { background-color: #0f172a; border: 1px solid #334155; border-radius: 6px; padding: 6px 12px; color: #f8fafc; }
QTableWidget, QTreeWidget { background-color: #0f172a; border: 1px solid #334155; border-radius: 8px; gridline-color: #1e293b; color: #f8fafc; selection-background-color: #2563eb; }
QHeaderView::section { background-color: #1e293b; color: #94a3b8; padding: 8px; font-weight: 600; border: none; border-bottom: 1px solid #334155; }
QProgressBar { background-color: #0f172a; border: 1px solid #334155; border-radius: 4px; text-align: center; color: #f8fafc; font-size: 11px; }
QProgressBar::chunk { background-color: #3b82f6; border-radius: 3px; }
QStatusBar { background-color: #0f172a; color: #94a3b8; border-top: 1px solid #334155; }
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_STYLESHEET)

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#0f172a"))
    palette.setColor(QPalette.WindowText, QColor("#f8fafc"))
    palette.setColor(QPalette.Base, QColor("#1e293b"))
    palette.setColor(QPalette.AlternateBase, QColor("#0f172a"))
    palette.setColor(QPalette.Text, QColor("#f8fafc"))
    palette.setColor(QPalette.Button, QColor("#1e293b"))
    palette.setColor(QPalette.ButtonText, QColor("#f8fafc"))
    palette.setColor(QPalette.Highlight, QColor("#2563eb"))
    palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)
