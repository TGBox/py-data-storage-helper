from typing import Optional
from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFrame, QMessageBox
)

from ...core.windows import is_running_as_admin
from ...core.database import DatabaseManager
from ...core.drive_detector import DriveDetector
from ...workers.defrag_worker import DefragWorker
from ..widgets.defrag_canvas import DefragClusterMapWidget


class DefragView(QWidget):
    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db
        self.worker: Optional[DefragWorker] = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header_layout = QHBoxLayout()
        title = QLabel("🧹 Festplatten-Defragmentierung & Cluster-Optimierer")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f8fafc;")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self.btn_refresh = QPushButton("Laufwerke aktualisieren")
        self.btn_refresh.setProperty("class", "action-secondary")
        self.btn_refresh.clicked.connect(self.refresh_drives)
        header_layout.addWidget(self.btn_refresh)
        layout.addLayout(header_layout)

        self.safety_banner = QFrame()
        self.safety_banner.setStyleSheet("background-color: #1e293b; border-radius: 8px; padding: 12px;")
        sb_layout = QVBoxLayout(self.safety_banner)

        select_row = QHBoxLayout()
        select_row.addWidget(QLabel("Zu optimierendes Laufwerk auswählen:"))
        self.combo_drives = QComboBox()
        self.combo_drives.currentIndexChanged.connect(self.on_drive_selected)
        select_row.addWidget(self.combo_drives, 1)
        sb_layout.addLayout(select_row)

        self.lbl_ssd_alert = QLabel()
        self.lbl_ssd_alert.setWordWrap(True)
        sb_layout.addWidget(self.lbl_ssd_alert)
        layout.addWidget(self.safety_banner)

        map_box = QGroupBox("🗺️ Physische Cluster-Belegungskarte (Sektor-Zustand)")
        map_box.setStyleSheet("QGroupBox { background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 10px; font-weight: 600; color: #f8fafc; }")
        mb_layout = QVBoxLayout(map_box)
        mb_layout.setContentsMargins(8, 8, 8, 8)
        mb_layout.setSpacing(8)

        legend_row = QHBoxLayout()
        legend_items = [
            ("Frei", "#1e293b"), ("Belegt", "#2563eb"), ("Fragmentiert", "#ef4444"),
            ("MFT / System", "#f59e0b"), ("Optimiert", "#06b6d4"), ("Schreibkopf", "#10b981")
        ]
        for name, col in legend_items:
            dot = QLabel(f"<span style='color:{col}; font-size:14px;'>■</span> {name}")
            dot.setStyleSheet("font-size: 11px; font-weight: 600; color: #cbd5e1;")
            legend_row.addWidget(dot)

        legend_row.addStretch()
        self.lbl_map_stats = QLabel("Bereit")
        self.lbl_map_stats.setStyleSheet("font-size: 11px; color: #94a3b8;")
        legend_row.addWidget(self.lbl_map_stats)
        mb_layout.addLayout(legend_row)

        self.cluster_map = DefragClusterMapWidget()
        mb_layout.addWidget(self.cluster_map)
        layout.addWidget(map_box)

        prog_box = QGroupBox("Optimierungs-Fortschritt")
        prog_box.setStyleSheet("QGroupBox { background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 10px; font-weight: 600; color: #f8fafc; }")
        pb_layout = QVBoxLayout(prog_box)
        pb_layout.setContentsMargins(8, 8, 8, 8)

        self.lbl_defrag_status = QLabel("Bereit für Analyse oder Defragmentierung.")
        self.lbl_defrag_status.setStyleSheet("color: #94a3b8; font-size: 12px;")
        self.prog_defrag = QProgressBar()
        self.prog_defrag.setRange(0, 100)
        self.prog_defrag.setValue(0)
        self.prog_defrag.setFixedHeight(12)
        pb_layout.addWidget(self.lbl_defrag_status)
        pb_layout.addWidget(self.prog_defrag)
        layout.addWidget(prog_box)

        layout.addWidget(QLabel("Live-Ausgabe der Windows Defrag Engine (defrag.exe):"))
        self.txt_console = QTextEdit()
        self.txt_console.setReadOnly(True)
        self.txt_console.setFixedHeight(100)
        self.txt_console.setStyleSheet("QTextEdit { background-color: #0b1120; border: 1px solid #334155; border-radius: 8px; font-family: 'Consolas'; color: #38bdf8; font-size: 11px; }")
        layout.addWidget(self.txt_console)

        btn_bar = QHBoxLayout()
        self.btn_analyze = QPushButton("📊 Nur Fragmentierung analysieren (/A)")
        self.btn_analyze.setProperty("class", "action-secondary")
        self.btn_analyze.clicked.connect(lambda: self.start_defrag(analyze_only=True))
        btn_bar.addWidget(self.btn_analyze)

        self.btn_execute = QPushButton("🚀 Vollständige Defragmentierung starten (/U /V)")
        self.btn_execute.setProperty("class", "action-primary")
        self.btn_execute.clicked.connect(lambda: self.start_defrag(analyze_only=False))
        btn_bar.addWidget(self.btn_execute)

        self.btn_abort = QPushButton("⏹️ Abbrechen")
        self.btn_abort.setProperty("class", "action-danger")
        self.btn_abort.setEnabled(False)
        self.btn_abort.clicked.connect(self.cancel_defrag)
        btn_bar.addWidget(self.btn_abort)
        btn_bar.addStretch()
        layout.addLayout(btn_bar)

        self.refresh_drives()

    def refresh_drives(self) -> None:
        self.combo_drives.clear()
        volumes = self.db.get_volumes() or DriveDetector.get_mounted_drives()
        for v in volumes:
            ssd_str = "SSD" if v.get("is_ssd") else "HDD"
            self.combo_drives.addItem(f"{v['letter']} [{v['label']}] - {ssd_str}", v)
        self.on_drive_selected()

    def on_drive_selected(self) -> None:
        data = self.combo_drives.currentData()
        if not data:
            return
        is_ssd = bool(data.get("is_ssd", 0))
        self.cluster_map.initialize_drive(data.get("total_space", 0), data.get("free_space", 0), is_ssd)

        if is_ssd:
            self.lbl_ssd_alert.setText("⚠️ <b>SSD-Schutz aktiv:</b> Defragmentierung auf Flash-Speichern ist gesperrt, um Zellverschleiß zu vermeiden.")
            self.lbl_ssd_alert.setStyleSheet("color: #f59e0b; font-size: 12px; margin-top: 4px;")
            self.btn_execute.setEnabled(False)
            self.btn_analyze.setEnabled(False)
            self.lbl_map_stats.setText("Flash-Speicher (SSD) - Defrag gesperrt.")
        else:
            self.lbl_ssd_alert.setText("✅ <b>Mechanische Festplatte (HDD):</b> Defragmentierung reorganisiert zusammenhängende Cluster.")
            self.lbl_ssd_alert.setStyleSheet("color: #10b981; font-size: 12px; margin-top: 4px;")
            self.btn_execute.setEnabled(True)
            self.btn_analyze.setEnabled(True)
            self.lbl_map_stats.setText(f"{self.cluster_map.total_blocks} Blöcke gerendert.")

    def start_defrag(self, analyze_only: bool) -> None:
        if not is_running_as_admin():
            QMessageBox.warning(self, "Admin erforderlich", "Die Ausführung von defrag.exe erfordert Administrator-Rechte.")
            return

        data = self.combo_drives.currentData()
        if not data:
            return

        self.txt_console.clear()
        self.prog_defrag.setValue(0)
        self.btn_analyze.setEnabled(False)
        self.btn_execute.setEnabled(False)
        self.btn_abort.setEnabled(True)
        self.lbl_defrag_status.setText(f"Defrag läuft für {data['letter']}...")
        self.cluster_map.start_animation()

        self.worker = DefragWorker(drive_letter=data["letter"], analyze_only=analyze_only)
        self.worker.sig_log_line.connect(self.txt_console.append)
        self.worker.sig_progress.connect(self.on_progress)
        self.worker.sig_finished.connect(self.on_finished)
        self.worker.start()

    def cancel_defrag(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.lbl_defrag_status.setText("Abbruch durch Benutzer...")
            self.cluster_map.complete_defrag()

    @Slot(int, str)
    def on_progress(self, pct: int, msg: str) -> None:
        self.prog_defrag.setValue(pct)
        self.lbl_defrag_status.setText(msg[:80])
        self.cluster_map.update_progress(pct, msg)

    @Slot(bool, str)
    def on_finished(self, success: bool, msg: str) -> None:
        self.btn_abort.setEnabled(False)
        self.cluster_map.complete_defrag()
        self.on_drive_selected()
        self.lbl_defrag_status.setText(f"Fertig: {msg}")

