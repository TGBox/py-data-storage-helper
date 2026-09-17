from typing import List, Dict, Any
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTreeWidget, QTreeWidgetItem, QHeaderView
)
from ...core.utils import format_bytes


class DryRunSimulationDialog(QDialog):
    def __init__(self, parent: QWidget, files_to_delete: List[Dict[str, Any]], total_reclaimable: int):
        super().__init__(parent)
        self.setWindowTitle("Simulationsansicht: Bereinigung & Datenverlust-Schutz")
        self.resize(850, 550)
        self.files_to_delete = files_to_delete

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        header_frame = QFrame()
        header_frame.setStyleSheet("background-color: #1e293b; border-radius: 8px; padding: 14px;")
        h_layout = QVBoxLayout(header_frame)

        title = QLabel("🛡️ Bereinigungs-Simulation & Sicherheitsprüfung")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #38bdf8;")
        h_layout.addWidget(title)

        summary_lbl = QLabel(
            f"Es wurden <b>{len(files_to_delete)}</b> Duplikate zum Entfernen markiert.<br>"
            f"Potentieller Speicherplatzgewinn: <span style='color: #10b981; font-size: 14px; font-weight: 700;'>"
            f"{format_bytes(total_reclaimable)}</span>"
        )
        summary_lbl.setStyleSheet("color: #cbd5e1; font-size: 13px;")
        h_layout.addWidget(summary_lbl)
        layout.addWidget(header_frame)

        self.chk_recycle = QCheckBox("In den Windows-Papierkorb verschieben (Sicherer Schutz vor versehentlichem Löschen)")
        self.chk_recycle.setChecked(True)
        self.chk_recycle.setStyleSheet("font-weight: 600; color: #f8fafc;")
        layout.addWidget(self.chk_recycle)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Dateiname", "Größe", "Änderungsdatum", "Vollständiger Pfad"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setRowCount(len(files_to_delete))

        for idx, item in enumerate(files_to_delete):
            self.table.setItem(idx, 0, QTableWidgetItem(item.get("name", "")))
            self.table.setItem(idx, 1, QTableWidgetItem(format_bytes(item.get("size", 0))))
            dt_str = datetime.datetime.fromtimestamp(item.get("mtime", 0)).strftime("%Y-%m-%d %H:%M")
            self.table.setItem(idx, 2, QTableWidgetItem(dt_str))
            self.table.setItem(idx, 3, QTableWidgetItem(item.get("abs_path", "")))

        layout.addWidget(self.table)

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        btn_cancel = QPushButton("Abbrechen")
        btn_cancel.setProperty("class", "action-secondary")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        self.btn_execute = QPushButton(f"Verbindlich bereinigen ({format_bytes(total_reclaimable)})")
        self.btn_execute.setProperty("class", "action-danger")
        self.btn_execute.clicked.connect(self.accept)
        btn_box.addWidget(self.btn_execute)
        layout.addLayout(btn_box)

