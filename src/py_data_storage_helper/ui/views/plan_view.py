from PySide6.QtGui import QColor
from typing import Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog, QMessageBox
)

from ...constants import PLAN_FILE_EXTENSION
from ...core.utils import format_bytes
from ...core.database import DatabaseManager
from ...core.plan import StoragePlan


class PlanManagerView(QWidget):
    sig_request_execution = Signal()

    def __init__(self, db: DatabaseManager, plan: StoragePlan):
        super().__init__()
        self.db = db
        self.current_plan = plan

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Speicher-Planung & .stplan Export/Import")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f8fafc;")
        layout.addWidget(title)

        action_bar = QHBoxLayout()
        btn_add_sample = QPushButton("+ Probe-Operation hinzufügen")
        btn_add_sample.setProperty("class", "action-secondary")
        btn_add_sample.clicked.connect(self.add_sample_operation)
        action_bar.addWidget(btn_add_sample)

        btn_clear = QPushButton("Plan leeren")
        btn_clear.setProperty("class", "action-secondary")
        btn_clear.clicked.connect(self.clear_plan)
        action_bar.addWidget(btn_clear)
        action_bar.addStretch()

        btn_save = QPushButton("Plan speichern (.stplan)")
        btn_save.setProperty("class", "action-secondary")
        btn_save.clicked.connect(self.save_plan_dialog)
        action_bar.addWidget(btn_save)

        btn_load = QPushButton("Plan laden (.stplan)")
        btn_load.setProperty("class", "action-secondary")
        btn_load.clicked.connect(self.load_plan_dialog)
        action_bar.addWidget(btn_load)

        self.btn_run_queue = QPushButton("🚀 Plan in Transfer-Queue ausführen")
        self.btn_run_queue.setProperty("class", "action-primary")
        self.btn_run_queue.clicked.connect(self.sig_request_execution.emit)
        action_bar.addWidget(self.btn_run_queue)
        layout.addLayout(action_bar)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["ID", "Typ", "Quelldatei / Ordner", "Ziel-Laufwerk / Pfad", "Größe", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)

        self.lbl_plan_summary = QLabel("Keine Operationen im aktuellen Plan.")
        self.lbl_plan_summary.setStyleSheet("color: #94a3b8;")
        layout.addWidget(self.lbl_plan_summary)
        self.refresh_table()

    def set_plan(self, plan: StoragePlan) -> None:
        self.current_plan = plan
        self.refresh_table()

    def clear_plan(self) -> None:
        self.current_plan.operations.clear()
        self.refresh_table()

    def add_sample_operation(self) -> None:
        self.current_plan.add_operation(
            op_type="MOVE", src_vol="C:", src_path="Videos/Raw_Project_01.mp4",
            tgt_vol="E:", tgt_path="Archive/Videos/Raw_Project_01.mp4", size=4_850_000_000
        )
        self.refresh_table()

    def refresh_table(self) -> None:
        ops = self.current_plan.operations
        self.table.setRowCount(len(ops))
        total_bytes = 0
        for idx, op in enumerate(ops):
            total_bytes += op.get("size", 0)
            self.table.setItem(idx, 0, QTableWidgetItem(op.get("op_id", "")))
            self.table.setItem(idx, 1, QTableWidgetItem(op.get("type", "MOVE")))
            self.table.setItem(idx, 2, QTableWidgetItem(f"{op.get('source_volume', '')} -> {op.get('source_path', '')}"))
            self.table.setItem(idx, 3, QTableWidgetItem(f"{op.get('target_volume', '')} -> {op.get('target_path', '')}"))
            self.table.setItem(idx, 4, QTableWidgetItem(format_bytes(op.get("size", 0))))
            status_item = QTableWidgetItem(op.get("status", "PENDING"))
            status_item.setForeground(QColor("#38bdf8"))
            self.table.setItem(idx, 5, status_item)

        self.lbl_plan_summary.setText(f"Plan: '{self.current_plan.name}' | {len(ops)} Operationen | Transfervolumen: {format_bytes(total_bytes)}")

    def save_plan_dialog(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Plan speichern", f"{self.current_plan.name}{PLAN_FILE_EXTENSION}", "Storage Plan (*.stplan)")
        if path and self.current_plan.save_to_file(path):
            QMessageBox.information(self, "Gespeichert", f"Plan erfolgreich gespeichert:\n{path}")

    def load_plan_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Plan laden", "", "Storage Plan (*.stplan)")
        if path:
            plan = StoragePlan.load_from_file(path)
            if plan:
                self.set_plan(plan)
                QMessageBox.information(self, "Geladen", f"Plan '{plan.name}' mit {len(plan.operations)} Aufgaben geladen.")

