import os
from typing import Dict, Any, Optional
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView,
    QFrame, QMessageBox
)

from ...core.utils import format_bytes
from ...core.database import DatabaseManager
from ...core.drive_detector import DriveDetector
from ...core.ejector import DriveEjector
from ...workers.indexer import IndexerWorker


class DriveOverviewView(QWidget):
    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db
        self.active_worker: Optional[IndexerWorker] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        header_layout = QHBoxLayout()
        title = QLabel("Laufwerks-Übersicht & Indizierung")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f8fafc;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        btn_refresh = QPushButton("Laufwerke neu erkennen")
        btn_refresh.setProperty("class", "action-secondary")
        btn_refresh.clicked.connect(self.refresh_drives)
        header_layout.addWidget(btn_refresh)

        self.btn_sim_usb = QPushButton("🔌 Simuliere USB-Laufwerk")
        self.btn_sim_usb.setProperty("class", "action-secondary")
        self.btn_sim_usb.clicked.connect(self.simulate_usb_connection)
        header_layout.addWidget(self.btn_sim_usb)
        layout.addLayout(header_layout)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(["Laufwerk", "Bezeichnung", "Typ", "Dateisystem", "Belegung / Kapazität", "Zustand", "Aktion"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.table)

        self.progress_group = QGroupBox("Aktive Indizierung")
        self.progress_group.setStyleSheet("QGroupBox { background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 16px; font-weight: 600; color: #f8fafc; }")
        prog_layout = QVBoxLayout(self.progress_group)
        self.lbl_prog_status = QLabel("Bereit für Scan.")
        self.lbl_prog_status.setStyleSheet("color: #94a3b8;")
        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 0)

        btn_box = QHBoxLayout()
        self.btn_cancel_scan = QPushButton("Indizierung abbrechen")
        self.btn_cancel_scan.setProperty("class", "action-danger")
        self.btn_cancel_scan.clicked.connect(self.cancel_current_scan)
        self.btn_cancel_scan.setEnabled(False)
        btn_box.addStretch()
        btn_box.addWidget(self.btn_cancel_scan)

        prog_layout.addWidget(self.lbl_prog_status)
        prog_layout.addWidget(self.prog_bar)
        prog_layout.addLayout(btn_box)
        layout.addWidget(self.progress_group)
        self.refresh_drives()

    def refresh_drives(self) -> None:
        drives = DriveDetector.get_mounted_drives()
        self.table.setRowCount(len(drives))
        for row, drv in enumerate(drives):
            self.db.upsert_volume(drv)
            self.table.setItem(row, 0, QTableWidgetItem(drv["letter"]))
            self.table.setItem(row, 1, QTableWidgetItem(drv["label"]))
            self.table.setItem(row, 2, QTableWidgetItem(f"{drv['drive_type']} ({'SSD' if drv.get('is_ssd') else 'HDD'})"))
            self.table.setItem(row, 3, QTableWidgetItem(drv["file_system"]))

            total = drv["total_space"]
            free = drv["free_space"]
            used = max(0, total - free)
            pct = int((used / total * 100)) if total > 0 else 0

            space_widget = QWidget()
            s_layout = QVBoxLayout(space_widget)
            s_layout.setContentsMargins(4, 4, 4, 4)
            s_bar = QProgressBar()
            s_bar.setRange(0, 100)
            s_bar.setValue(pct)
            s_lbl = QLabel(f"{format_bytes(used)} / {format_bytes(total)} ({pct} %)")
            s_lbl.setStyleSheet("font-size: 11px; color: #94a3b8;")
            s_layout.addWidget(s_bar)
            s_layout.addWidget(s_lbl)
            self.table.setCellWidget(row, 4, space_widget)
            self.table.setItem(row, 5, QTableWidgetItem("🟢 " + drv.get("smart_status", "OK")))

            action_widget = QWidget()
            act_layout = QHBoxLayout(action_widget)
            act_layout.setContentsMargins(4, 2, 4, 2)
            act_layout.setSpacing(6)

            btn_scan = QPushButton("Indizieren")
            btn_scan.setProperty("class", "action-primary")
            btn_scan.clicked.connect(lambda chk=False, d=drv: self.start_indexing(d))
            act_layout.addWidget(btn_scan)

            if drv.get("drive_type") == "Removable" or "C:" not in drv.get("letter", ""):
                btn_eject = QPushButton("⏏ Auswerfen")
                btn_eject.setProperty("class", "action-secondary")
                btn_eject.clicked.connect(lambda chk=False, d=drv: self.eject_drive(d))
                act_layout.addWidget(btn_eject)

            self.table.setCellWidget(row, 6, action_widget)

    def eject_drive(self, drv: Dict[str, Any]) -> None:
        success, msg = DriveEjector.safely_eject_drive(drv.get("letter", ""))
        QMessageBox.information(self, "Auswerfen", msg)
        self.refresh_drives()

    def simulate_usb_connection(self) -> None:
        sim_id = f"VOL_USB_{int(time.time()) % 10000}"
        sim_drive = {
            "id": sim_id, "label": "SanDisk_Ultra_USB", "letter": "F:\\",
            "total_space": 128 * 1024**3, "free_space": 74 * 1024**3,
            "file_system": "exFAT", "is_ssd": 0, "drive_type": "Removable", "smart_status": "OK"
        }
        main_win = self.window()
        if hasattr(main_win, 'device_watcher'):
            main_win.device_watcher.trigger_simulated_arrival(sim_drive)

    def start_indexing(self, drive_dict: Dict[str, Any]) -> None:
        if self.active_worker and self.active_worker.isRunning():
            QMessageBox.warning(self, "Vorgang läuft", "Es läuft bereits eine Indizierung.")
            return
        vol_id = drive_dict["id"]
        root_path = drive_dict["letter"]
        self.db.delete_volume_files(vol_id)
        self.lbl_prog_status.setText(f"Indiziere {root_path} ({drive_dict['label']})...")
        self.prog_bar.setRange(0, 0)
        self.btn_cancel_scan.setEnabled(True)

        self.active_worker = IndexerWorker(vol_id, root_path)
        self.active_worker.sig_batch_ready.connect(self.db.insert_files_batch)
        self.active_worker.sig_progress.connect(self.on_indexer_progress)
        self.active_worker.sig_finished.connect(self.on_indexer_finished)
        self.active_worker.sig_error.connect(self.on_indexer_error)
        self.active_worker.start()

    @Slot(int, int, str)
    def on_indexer_progress(self, file_count: int, total_size: int, current_path: str) -> None:
        self.lbl_prog_status.setText(f"Gefunden: {file_count:,} Dateien ({format_bytes(total_size)}) | {current_path[:75]}")

    @Slot(dict)
    def on_indexer_finished(self, summary: dict) -> None:
        self.btn_cancel_scan.setEnabled(False)
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(100)
        self.lbl_prog_status.setText(f"Fertig: {summary['file_count']:,} Dateien ({format_bytes(summary['total_size'])})")
        QMessageBox.information(self, "Indizierung fertig", f"Dateien: {summary['file_count']:,}\nGröße: {format_bytes(summary['total_size'])}")

    @Slot(str)
    def on_indexer_error(self, err_msg: str) -> None:
        self.btn_cancel_scan.setEnabled(False)
        self.lbl_prog_status.setText(f"Fehler: {err_msg}")

    def cancel_current_scan(self) -> None:
        if self.active_worker:
            self.lbl_prog_status.setText("Abbruch angefordert...")
            self.active_worker.cancel()

