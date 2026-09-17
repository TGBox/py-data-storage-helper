import sys
from PySide6.QtWidgets import QTextEdit
from PySide6.QtWidgets import QGroupBox
import os
import platform
from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QMessageBox
)

from ...core.windows import is_running_as_admin, WindowsPowerManager
from ...core.database import DatabaseManager
from ..widgets.admin_banner import StatCard


class SystemStatusView(QWidget):
    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        title = QLabel("System-Status & Diagnostik")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f8fafc;")
        layout.addWidget(title)

        cards_layout = QHBoxLayout()
        self.card_admin = StatCard("Berechtigungen", "Admin" if is_running_as_admin() else "User", "UAC Status")
        self.card_power = StatCard("Power Manager", "Inaktiv", "Sleep Prevention")
        self.card_db = StatCard("SQLite Datenbank", "WAL Aktiv", os.path.basename(self.db.db_path))
        cards_layout.addWidget(self.card_admin)
        cards_layout.addWidget(self.card_power)
        cards_layout.addWidget(self.card_db)
        layout.addLayout(cards_layout)

        group_diag = QGroupBox("Windows API & Pfadkonfiguration")
        group_diag.setStyleSheet("QGroupBox { background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 16px; font-weight: 600; color: #f8fafc; }")
        diag_layout = QVBoxLayout(group_diag)

        self.txt_info = QTextEdit()
        self.txt_info.setReadOnly(True)
        self.txt_info.setStyleSheet("background-color: #0f172a; border: 1px solid #334155; color: #cbd5e1;")
        info_str = (
            f"Betriebssystem: {platform.system()} {platform.release()} ({platform.architecture()[0]})\n"
            f"Python Version: {sys.version}\n"
            f"Datenbankpfad: {self.db.db_path}\n"
            f"Long-Path-Unterstützung (\\\\?\\): Aktiviert\n"
            f"NTFS Reparse-Point / Junction-Schutz: Aktiviert\n"
            f"Admin-Rechte: {'Ja (Vollzugriff)' if is_running_as_admin() else 'Nein (Eingeschränkter Modus)'}\n"
            f"Hardware-Event-Watcher: Aktiv (WM_DEVICECHANGE)\n"
        )
        self.txt_info.setText(info_str)
        diag_layout.addWidget(self.txt_info)

        btn_power_toggle = QPushButton("Sleep-Prevention Testen (An/Aus)")
        btn_power_toggle.setProperty("class", "action-secondary")
        btn_power_toggle.clicked.connect(self.toggle_power_management)
        diag_layout.addWidget(btn_power_toggle)
        layout.addWidget(group_diag)
        layout.addStretch()

    def toggle_power_management(self) -> None:
        if WindowsPowerManager.is_active():
            WindowsPowerManager.allow_sleep()
            self.card_power.set_value("Inaktiv", "Sleep erlaubt")
        else:
            ok = WindowsPowerManager.prevent_sleep()
            self.card_power.set_value("Aktiv", "Sleep unterdrückt" if ok else "Nicht unterstützt")

