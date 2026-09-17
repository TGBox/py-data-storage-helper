from PySide6.QtGui import QColor
import os
import shutil
from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox
)

from ...core.database import DatabaseManager


class UndoJournalView(QWidget):
    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Transaktions- & Undo-Journal")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f8fafc;")
        layout.addWidget(title)

        bar = QHBoxLayout()
        btn_refresh = QPushButton("Historie aktualisieren")
        btn_refresh.setProperty("class", "action-secondary")
        btn_refresh.clicked.connect(self.refresh_logs)
        bar.addWidget(btn_refresh)

        btn_rollback = QPushButton("Ausgewählte Aktion rückgängig machen (Rollback)")
        btn_rollback.setProperty("class", "action-danger")
        btn_rollback.clicked.connect(self.rollback_selected)
        bar.addWidget(btn_rollback)
        bar.addStretch()
        layout.addLayout(bar)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["ID", "Zeitpunkt", "Operation", "Quelle", "Ziel", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.table)
        self.refresh_logs()

    def refresh_logs(self) -> None:
        logs = self.db.get_operation_logs(100)
        self.table.setRowCount(len(logs))
        for idx, row in enumerate(logs):
            self.table.setItem(idx, 0, QTableWidgetItem(str(row["id"])))
            self.table.setItem(idx, 1, QTableWidgetItem(str(row["timestamp"])))
            self.table.setItem(idx, 2, QTableWidgetItem(row["operation_type"]))
            self.table.setItem(idx, 3, QTableWidgetItem(row["source_path"]))
            self.table.setItem(idx, 4, QTableWidgetItem(row["target_path"] or "-"))

            reverted = row["reverted"] == 1
            status_item = QTableWidgetItem("Rückgängig gemacht" if reverted else "Aktiv")
            status_item.setForeground(QColor("#94a3b8" if reverted else "#10b981"))
            self.table.setItem(idx, 5, status_item)

    def rollback_selected(self) -> None:
        sel = self.table.currentRow()
        if sel < 0:
            QMessageBox.warning(self, "Keine Auswahl", "Bitte wählen Sie eine Zeile aus.")
            return
        op_id = int(self.table.item(sel, 0).text())
        confirm = QMessageBox.question(self, "Rollback bestätigen", f"Möchten Sie Operation #{op_id} physisch rückgängig machen?", QMessageBox.Yes | QMessageBox.No)
        if confirm == QMessageBox.Yes:
            success, message = self.db.execute_physical_rollback(op_id)
            self.refresh_logs()
            QMessageBox.information(self, "Ergebnis", message)

