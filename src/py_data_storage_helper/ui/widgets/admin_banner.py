from typing import Optional
from PySide6.QtWidgets import QVBoxLayout
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Signal


class AdminBanner(QFrame):
    sig_request_elevation = Signal()

    def __init__(self, is_admin: bool):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        self.status_icon = QLabel()
        self.status_text = QLabel()
        self.action_btn = QPushButton("Plan sichern & als Admin neustarten")
        self.action_btn.clicked.connect(self.sig_request_elevation.emit)

        layout.addWidget(self.status_icon)
        layout.addWidget(self.status_text, 1)
        layout.addWidget(self.action_btn)
        self.update_status(is_admin)

    def update_status(self, is_admin: bool) -> None:
        if is_admin:
            self.setStyleSheet("QFrame { background-color: #064e3b; border-bottom: 1px solid #059669; } QLabel { color: #a7f3d0; font-weight: 600; font-size: 13px; }")
            self.status_icon.setText("🛡️")
            self.status_text.setText("Administrator-Modus: Vollzugriff auf Hardware und Defragmentierung aktiv.")
            self.action_btn.setVisible(False)
        else:
            self.setStyleSheet("QFrame { background-color: #78350f; border-bottom: 1px solid #d97706; } QLabel { color: #fef3c7; font-size: 13px; font-weight: 500; } QPushButton { background-color: #d97706; color: #fff; border-radius: 6px; padding: 6px 14px; font-weight: 600; border: none; }")
            self.status_icon.setText("⚠️")
            self.status_text.setText("Eingeschränkter Modus: Nur Planung und Analyse aktiv. Ausführung erfordert Adminrechte.")
            self.action_btn.setVisible(True)



class StatCard(QFrame):
    def __init__(self, title: str, value: str = "0", subtitle: str = ""):
        super().__init__()
        self.setStyleSheet("QFrame { background-color: #1e293b; border: 1px solid #334155; border-radius: 10px; padding: 12px; }")
        layout = QVBoxLayout(self)
        layout.setSpacing(4)
        self.lbl_title = QLabel(title)
        self.lbl_title.setStyleSheet("color: #94a3b8; font-size: 12px; font-weight: 600; text-transform: uppercase;")
        self.lbl_val = QLabel(value)
        self.lbl_val.setStyleSheet("color: #f8fafc; font-size: 20px; font-weight: 700;")
        self.lbl_sub = QLabel(subtitle)
        self.lbl_sub.setStyleSheet("color: #64748b; font-size: 11px;")
        layout.addWidget(self.lbl_title)
        layout.addWidget(self.lbl_val)
        layout.addWidget(self.lbl_sub)

    def set_value(self, val: str, sub: Optional[str] = None) -> None:
        self.lbl_val.setText(val)
        if sub is not None:
            self.lbl_sub.setText(sub)

