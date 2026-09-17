from typing import Optional
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QComboBox, QCheckBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox
)

from ...core.utils import format_bytes
from ...core.database import DatabaseManager
from ...core.drive_detector import DriveDetector
from ...core.smart import SmartHealthChecker
from ...core.plan import StoragePlan
from ...workers.transfer import SpindleAwareTransferCoordinator
from ..widgets.admin_banner import StatCard


class TransferQueueView(QWidget):
    def __init__(self, db: DatabaseManager, plan: StoragePlan):
        super().__init__()
        self.db = db
        self.plan = plan
        self.worker: Optional[SpindleAwareTransferCoordinator] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header_bar = QHBoxLayout()
        title = QLabel("🚀 Spindle-Aware Transfer-Queue & Parallele Ausführung")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f8fafc;")
        header_bar.addWidget(title)
        header_bar.addStretch()

        self.btn_smart_check = QPushButton("🩺 S.M.A.R.T. Vorab-Prüfung")
        self.btn_smart_check.setProperty("class", "action-secondary")
        self.btn_smart_check.clicked.connect(self.run_smart_preflight)
        header_bar.addWidget(self.btn_smart_check)
        layout.addLayout(header_bar)

        opt_box = QGroupBox("Spindle-Aware Concurrency & Resilienz-Einstellungen")
        opt_box.setStyleSheet("QGroupBox { background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 12px; font-weight: 600; color: #f8fafc; }")
        opt_layout = QVBoxLayout(opt_box)
        opt_layout.setSpacing(8)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Konfliktlösung:"))
        self.combo_conflict = QComboBox()
        self.combo_conflict.addItem("Automatisch versionieren (Kopie)", "VERSION")
        self.combo_conflict.addItem("Überschreiben", "OVERWRITE")
        self.combo_conflict.addItem("Überspringen", "SKIP")
        self.combo_conflict.addItem("Nur aktualisieren (wenn neuer)", "UPDATE")
        row1.addWidget(self.combo_conflict)

        self.chk_checksum = QCheckBox("In-Flight SHA-256 verifizieren")
        self.chk_checksum.setChecked(True)
        self.chk_checksum.setStyleSheet("color: #38bdf8; font-weight: 600;")
        row1.addWidget(self.chk_checksum)

        self.chk_timestamps = QCheckBox("NTFS-Zeitstempel erhalten")
        self.chk_timestamps.setChecked(True)
        row1.addWidget(self.chk_timestamps)
        row1.addStretch()
        opt_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self.chk_hdd_lock = QCheckBox("🔒 HDD Spindelschutz aktiv (Streng 1 Stream/Spindel zur Vermeidung von Head-Thrashing)")
        self.chk_hdd_lock.setChecked(True)
        self.chk_hdd_lock.setStyleSheet("color: #10b981; font-weight: 600;")
        row2.addWidget(self.chk_hdd_lock)

        row2.addSpacing(16)
        row2.addWidget(QLabel("SSD/NVMe Parallel-Streams:"))
        self.spin_ssd_concurrency = QSpinBox()
        self.spin_ssd_concurrency.setRange(1, 4)
        self.spin_ssd_concurrency.setValue(3)
        row2.addWidget(self.spin_ssd_concurrency)
        row2.addStretch()
        opt_layout.addLayout(row2)
        layout.addWidget(opt_box)

        self.telemetry_frame = QFrame()
        self.telemetry_frame.setStyleSheet("background-color: #0f172a; border: 1px solid #334155; border-radius: 8px; padding: 10px;")
        self.telemetry_layout = QHBoxLayout(self.telemetry_frame)
        self.telemetry_layout.setContentsMargins(8, 4, 8, 4)
        self.lbl_spindle_status = QLabel("📊 Physische Spindeln: Bereit.")
        self.lbl_spindle_status.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.telemetry_layout.addWidget(self.lbl_spindle_status)
        layout.addWidget(self.telemetry_frame)

        metrics_layout = QHBoxLayout()
        self.card_speed = StatCard("Gesamtdurchsatz", "0.0 MB/s", "Live I/O Aggregiert")
        self.card_eta = StatCard("Verbleibende Zeit", "--:--:--", "Geschätzte Dauer")
        self.card_volume = StatCard("Datenmenge", "0 B / 0 B", "Fortschritt gesamt")
        metrics_layout.addWidget(self.card_speed)
        metrics_layout.addWidget(self.card_eta)
        metrics_layout.addWidget(self.card_volume)
        layout.addLayout(metrics_layout)

        prog_frame = QFrame()
        prog_frame.setStyleSheet("background-color: #1e293b; border-radius: 8px; padding: 12px;")
        p_layout = QVBoxLayout(prog_frame)
        p_layout.setSpacing(6)

        self.lbl_overall_status = QLabel("Warteschlange bereit.")
        self.lbl_overall_status.setStyleSheet("font-weight: 600; color: #f8fafc;")
        self.bar_overall = QProgressBar()
        self.bar_overall.setRange(0, 100)
        self.bar_overall.setValue(0)
        p_layout.addWidget(self.lbl_overall_status)
        p_layout.addWidget(self.bar_overall)
        layout.addWidget(prog_frame)

        active_group = QGroupBox("⚡ Aktive parallele Datenströme (Spindle Channels)")
        active_group.setStyleSheet("QGroupBox { background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 10px; font-weight: 600; color: #f8fafc; }")
        ag_layout = QVBoxLayout(active_group)
        ag_layout.setContentsMargins(8, 8, 8, 8)

        self.table_active_streams = QTableWidget()
        self.table_active_streams.setColumnCount(6)
        self.table_active_streams.setHorizontalHeaderLabels(["ID", "Datei", "Quelle ➔ Ziel Disk", "Fortschritt", "Rate", "Übertragen"])
        self.table_active_streams.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_active_streams.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table_active_streams.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.table_active_streams.setFixedHeight(115)
        self.table_active_streams.verticalHeader().setVisible(False)
        ag_layout.addWidget(self.table_active_streams)
        layout.addWidget(active_group)

        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["ID", "Typ", "Quelle", "Ziel", "Größe", "Status"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, 1)

        control_bar = QHBoxLayout()
        self.btn_start = QPushButton("🚀 Transfer jetzt starten")
        self.btn_start.setProperty("class", "action-primary")
        self.btn_start.setFixedHeight(36)
        self.btn_start.clicked.connect(self.start_transfer)
        control_bar.addWidget(self.btn_start)

        self.btn_pause = QPushButton("⏸️ Pausieren")
        self.btn_pause.setProperty("class", "action-secondary")
        self.btn_pause.setEnabled(False)
        self.btn_pause.clicked.connect(self.toggle_pause)
        control_bar.addWidget(self.btn_pause)

        self.btn_cancel = QPushButton("⏹️ Abbrechen")
        self.btn_cancel.setProperty("class", "action-danger")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_transfer)
        control_bar.addWidget(self.btn_cancel)
        control_bar.addStretch()
        layout.addLayout(control_bar)

        self.refresh_table()

    def refresh_table(self) -> None:
        ops = self.plan.operations
        self.table.setRowCount(len(ops))
        total_b = sum(o.get("size", 0) for o in ops)
        self.card_volume.set_value(f"0 B / {format_bytes(total_b)}", f"{len(ops)} Aufgaben")

        for idx, op in enumerate(ops):
            self.table.setItem(idx, 0, QTableWidgetItem(op.get("op_id", "")))
            self.table.setItem(idx, 1, QTableWidgetItem(op.get("type", "MOVE")))
            self.table.setItem(idx, 2, QTableWidgetItem(f"{op.get('source_volume', '')} -> {op.get('source_path', '')}"))
            self.table.setItem(idx, 3, QTableWidgetItem(f"{op.get('target_volume', '')} -> {op.get('target_path', '')}"))
            self.table.setItem(idx, 4, QTableWidgetItem(format_bytes(op.get("size", 0))))
            status_item = QTableWidgetItem(op.get("status", "PENDING"))
            status_item.setForeground(QColor("#38bdf8"))
            self.table.setItem(idx, 5, status_item)

    def run_smart_preflight(self) -> None:
        volumes = self.db.get_volumes() or DriveDetector.get_mounted_drives()
        warnings = []
        for v in volumes:
            check = SmartHealthChecker.check_drive_health(v["letter"])
            if check["warning"]:
                warnings.append(f"{v['letter']} ({v['label']}): {check['message']}")

        if warnings:
            QMessageBox.warning(self, "S.M.A.R.T. Warnung", "Laufwerke melden Warnungen:\n" + "\n".join(warnings))
        else:
            QMessageBox.information(self, "S.M.A.R.T. OK", "Alle beteiligten Laufwerke melden normalen Gesundheitszustand ('Healthy').")

    def start_transfer(self) -> None:
        if not self.plan.operations:
            QMessageBox.warning(self, "Keine Aufgaben", "Der aktuelle Plan enthält keine zu übertragenden Operationen.")
            return

        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_cancel.setEnabled(True)

        self.worker = SpindleAwareTransferCoordinator(
            plan=self.plan, db=self.db,
            conflict_strategy=self.combo_conflict.currentData(),
            verify_checksum=self.chk_checksum.isChecked(),
            preserve_timestamps=self.chk_timestamps.isChecked(),
            ssd_concurrency=self.spin_ssd_concurrency.value(),
            strict_hdd_lock=self.chk_hdd_lock.isChecked()
        )
        self.worker.sig_overall_progress.connect(self.on_overall_progress)
        self.worker.sig_active_streams.connect(self.on_active_streams_update)
        self.worker.sig_spindle_telemetry.connect(self.on_spindle_telemetry_update)
        self.worker.sig_item_completed.connect(self.on_item_completed)
        self.worker.sig_finished.connect(self.on_transfer_finished)
        self.worker.start()

    def toggle_pause(self) -> None:
        if self.worker:
            paused = self.worker.toggle_pause()
            self.btn_pause.setText("▶️ Fortsetzen" if paused else "⏸️ Pausieren")

    def cancel_transfer(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.btn_cancel.setEnabled(False)

    @Slot(int, int, int, int, float, str)
    def on_overall_progress(self, cur_ops: int, total_ops: int, cur_bytes: int, total_bytes: int, speed: float, eta: str) -> None:
        pct = int((cur_bytes / max(1, total_bytes)) * 100)
        self.bar_overall.setValue(pct)
        self.lbl_overall_status.setText(f"Fortschritt: {cur_ops}/{total_ops} Aufgaben ({pct}%) | Noch {eta}")
        self.card_speed.set_value(f"{format_bytes(speed)}/s")
        self.card_eta.set_value(eta)
        self.card_volume.set_value(f"{format_bytes(cur_bytes)} / {format_bytes(total_bytes)}")

    @Slot(list)
    def on_active_streams_update(self, streams: list) -> None:
        self.table_active_streams.setRowCount(len(streams))
        for r, s in enumerate(streams):
            self.table_active_streams.setItem(r, 0, QTableWidgetItem(s["op_id"]))
            self.table_active_streams.setItem(r, 1, QTableWidgetItem(s["name"]))
            self.table_active_streams.setItem(r, 2, QTableWidgetItem(f"{s['src_disk']} ➔ {s['tgt_disk']}"))

            bar_widget = QProgressBar()
            bar_widget.setRange(0, 100)
            bar_widget.setValue(s["pct"])
            bar_widget.setFixedHeight(12)
            self.table_active_streams.setCellWidget(r, 3, bar_widget)
            self.table_active_streams.setItem(r, 4, QTableWidgetItem(f"{format_bytes(s['speed'])}/s"))
            self.table_active_streams.setItem(r, 5, QTableWidgetItem(f"{format_bytes(s['cur_bytes'])} / {format_bytes(s['total_bytes'])}"))

    @Slot(dict)
    def on_spindle_telemetry_update(self, telem: dict) -> None:
        badges = []
        for disk_id, d in telem.items():
            type_lbl = "SSD" if d["is_ssd"] else "HDD"
            status_color = "#10b981" if d["active"] < d["max"] else "#f59e0b"
            badges.append(f"<span style='color:#cbd5e1;'>{d['letter']} ({type_lbl}):</span> <b style='color:{status_color};'>[{d['active']}/{d['max']}]</b>")
        self.lbl_spindle_status.setText(" | ".join(badges) if badges else "Keine aktiven Festplattenzugriffe.")

    @Slot(str, str, str)
    def on_item_completed(self, op_id: str, status: str, msg: str) -> None:
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).text() == op_id:
                item = QTableWidgetItem(status)
                item.setForeground(QColor("#10b981" if status == "SUCCESS" else ("#f59e0b" if status == "SKIPPED" else "#ef4444")))
                self.table.setItem(row, 5, item)
                break

    @Slot(dict)
    def on_transfer_finished(self, summary: dict) -> None:
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.table_active_streams.setRowCount(0)
        self.lbl_spindle_status.setText("Transfer abgeschlossen. Alle Spindeln im Leerlauf.")
        self.card_speed.set_value("0.0 B/s", "Beendet")
        self.card_eta.set_value("Fertig")
        QMessageBox.information(
            self, "Transfer abgeschlossen",
            f"Vorgang beendet!\nErfolgreich: {summary.get('success_count')}\nFehlgeschlagen: {summary.get('failed_count')}\nÜbertragen: {format_bytes(summary.get('total_bytes', 0))}"
        )

