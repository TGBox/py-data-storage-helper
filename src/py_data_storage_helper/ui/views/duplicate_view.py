import os
from typing import List, Dict, Any, Optional
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QComboBox, QSpinBox, QSplitter,
    QTreeWidget, QTreeWidgetItem, QMessageBox
)

from ...core.utils import to_long_path, format_bytes
from ...core.windows import send_to_recycle_bin
from ...core.database import DatabaseManager
from ...workers.duplicate_worker import DuplicateFinderWorker
from ..widgets.dry_run_dialog import DryRunSimulationDialog


class DuplicateFinderView(QWidget):
    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db
        self.worker: Optional[DuplicateFinderWorker] = None
        self.duplicate_groups: List[Dict[str, Any]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        header_layout = QHBoxLayout()
        title = QLabel("Duplikaterkennung & Redundanz-Inspektor")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f8fafc;")
        header_layout.addWidget(title)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        filter_bar = QHBoxLayout()
        self.combo_volume = QComboBox()
        self.combo_volume.addItem("Alle Laufwerke", None)
        filter_bar.addWidget(self.combo_volume)

        self.combo_min_size = QComboBox()
        self.combo_min_size.addItem("Min: > 100 KB", 100 * 1024)
        self.combo_min_size.addItem("Min: > 1 MB", 1024 * 1024)
        self.combo_min_size.addItem("Min: > 10 MB", 10 * 1024 * 1024)
        self.combo_min_size.addItem("Min: > 100 MB", 100 * 1024 * 1024)
        self.combo_min_size.setCurrentIndex(1)
        filter_bar.addWidget(self.combo_min_size)

        self.combo_category = QComboBox()
        self.combo_category.addItems(["Alle Kategorien", "image", "video", "audio", "document", "archive", "code", "other"])
        filter_bar.addWidget(self.combo_category)

        self.combo_mode = QComboBox()
        self.combo_mode.addItem("Exakt (Byte-Identisch / SHA-256)", "EXACT")
        self.combo_mode.addItem("Fuzzy (Ähnliche Dateinamen)", "FUZZY")
        filter_bar.addWidget(self.combo_mode)

        self.btn_scan = QPushButton("Duplikate scannen")
        self.btn_scan.setProperty("class", "action-primary")
        self.btn_scan.clicked.connect(self.start_scan)
        filter_bar.addWidget(self.btn_scan)

        self.btn_cancel = QPushButton("Abbrechen")
        self.btn_cancel.setProperty("class", "action-danger")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_scan)
        filter_bar.addWidget(self.btn_cancel)
        layout.addLayout(filter_bar)

        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(0)
        self.lbl_status = QLabel("Bereit für Duplikatanalyse.")
        self.lbl_status.setStyleSheet("color: #94a3b8; font-size: 12px;")
        layout.addWidget(self.lbl_status)
        layout.addWidget(self.prog_bar)

        auto_sel_bar = QHBoxLayout()
        auto_sel_bar.addWidget(QLabel("Smarte Vorauswahl:"))

        btn_keep_oldest = QPushButton("Älteste behalten")
        btn_keep_oldest.setProperty("class", "action-secondary")
        btn_keep_oldest.clicked.connect(lambda: self.apply_selection_strategy("OLDEST"))
        auto_sel_bar.addWidget(btn_keep_oldest)

        btn_keep_newest = QPushButton("Neueste behalten")
        btn_keep_newest.setProperty("class", "action-secondary")
        btn_keep_newest.clicked.connect(lambda: self.apply_selection_strategy("NEWEST"))
        auto_sel_bar.addWidget(btn_keep_newest)

        btn_keep_shortest = QPushButton("Kürzesten Pfad behalten")
        btn_keep_shortest.setProperty("class", "action-secondary")
        btn_keep_shortest.clicked.connect(lambda: self.apply_selection_strategy("SHORTEST_PATH"))
        auto_sel_bar.addWidget(btn_keep_shortest)

        btn_clear_sel = QPushButton("Alle abwählen")
        btn_clear_sel.setProperty("class", "action-secondary")
        btn_clear_sel.clicked.connect(lambda: self.apply_selection_strategy("CLEAR"))
        auto_sel_bar.addWidget(btn_clear_sel)
        auto_sel_bar.addStretch()

        self.btn_dry_run = QPushButton("Bereinigung simulieren & ausführen...")
        self.btn_dry_run.setProperty("class", "action-danger")
        self.btn_dry_run.clicked.connect(self.open_simulation)
        auto_sel_bar.addWidget(self.btn_dry_run)
        layout.addLayout(auto_sel_bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Auswahl / Gruppe", "Größe", "Redundanz", "Änderungsdatum", "Pfad"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(4, QHeaderView.Stretch)
        layout.addWidget(self.tree)

    def refresh_volume_list(self) -> None:
        self.combo_volume.clear()
        self.combo_volume.addItem("Alle Laufwerke", None)
        for vol in self.db.get_volumes():
            self.combo_volume.addItem(f"{vol['letter']} [{vol['label']}]", vol["id"])

    def start_scan(self) -> None:
        if self.worker and self.worker.isRunning():
            return
        self.tree.clear()
        self.duplicate_groups.clear()
        self.btn_scan.setEnabled(False)
        self.btn_cancel.setEnabled(True)

        mode = self.combo_mode.currentData()
        vol_id = self.combo_volume.currentData()
        min_sz = self.combo_min_size.currentData()
        cat = self.combo_category.currentText()

        self.worker = DuplicateFinderWorker(self.db, mode=mode, volume_id=vol_id, min_size=min_sz, category=cat)
        self.worker.sig_progress.connect(self.on_worker_progress)
        self.worker.sig_duplicate_group.connect(self.on_group_found)
        self.worker.sig_finished.connect(self.on_scan_finished)
        self.worker.sig_error.connect(self.on_scan_error)
        self.worker.start()

    def cancel_scan(self) -> None:
        if self.worker:
            self.lbl_status.setText("Breche Duplikatsuche ab...")
            self.worker.cancel()

    @Slot(str, int, int)
    def on_worker_progress(self, msg: str, cur: int, total: int) -> None:
        self.lbl_status.setText(msg)
        if total > 0:
            self.prog_bar.setValue(int((cur / total) * 100))

    @Slot(dict)
    def on_group_found(self, grp: dict) -> None:
        self.duplicate_groups.append(grp)
        files = grp["files"]
        rep_file = files[0]

        top_item = QTreeWidgetItem(self.tree)
        top_item.setText(0, f"📁 Gruppe {len(self.duplicate_groups)}: {rep_file['name']} ({len(files)} Kopien)")
        top_item.setText(1, format_bytes(grp["size"]))
        top_item.setText(2, format_bytes(grp["wasted_bytes"]))
        top_item.setExpanded(True)
        top_item.setForeground(0, QColor("#38bdf8"))

        for idx, f in enumerate(files):
            child = QTreeWidgetItem(top_item)
            child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
            child.setCheckState(0, Qt.Checked if idx > 0 else Qt.Unchecked)
            child.setText(0, f["name"])
            child.setText(1, format_bytes(f["size"]))
            child.setText(2, "Duplikat" if idx > 0 else "Original (Behalten)")
            dt_str = datetime.datetime.fromtimestamp(f.get("mtime", 0)).strftime("%Y-%m-%d %H:%M")
            child.setText(3, dt_str)
            abs_p = f.get("abs_path") or os.path.join(f.get("volume_letter", ""), f.get("path", ""))
            child.setText(4, abs_p)
            child.setData(0, Qt.UserRole, f)

    @Slot(list, int)
    def on_scan_finished(self, groups: list, wasted_bytes: int) -> None:
        self.btn_scan.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.prog_bar.setValue(100)
        self.lbl_status.setText(f"Scan fertig: {len(groups)} Gruppen. Reclaimbarer Speicherplatz: {format_bytes(wasted_bytes)}.")

    @Slot(str)
    def on_scan_error(self, err: str) -> None:
        self.btn_scan.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.lbl_status.setText(f"Fehler: {err}")

    def apply_selection_strategy(self, strategy: str) -> None:
        root = self.tree.invisibleRootItem()
        for g_idx in range(root.childCount()):
            group_item = root.child(g_idx)
            children = [group_item.child(i) for i in range(group_item.childCount())]
            if not children:
                continue
            if strategy == "CLEAR":
                for c in children:
                    c.setCheckState(0, Qt.Unchecked)
                continue
            if strategy == "OLDEST":
                best = min(children, key=lambda c: c.data(0, Qt.UserRole).get("mtime", 0))
            elif strategy == "NEWEST":
                best = max(children, key=lambda c: c.data(0, Qt.UserRole).get("mtime", 0))
            elif strategy == "SHORTEST_PATH":
                best = min(children, key=lambda c: len(c.text(4)))
            else:
                best = children[0]
            for c in children:
                c.setCheckState(0, Qt.Unchecked if c == best else Qt.Checked)

    def open_simulation(self) -> None:
        root = self.tree.invisibleRootItem()
        selected_files: List[Dict[str, Any]] = []
        total_reclaimable = 0

        for g_idx in range(root.childCount()):
            group_item = root.child(g_idx)
            for c_idx in range(group_item.childCount()):
                child = group_item.child(c_idx)
                if child.checkState(0) == Qt.Checked:
                    f_data = child.data(0, Qt.UserRole)
                    if f_data:
                        f_data["abs_path"] = child.text(4)
                        selected_files.append(f_data)
                        total_reclaimable += f_data.get("size", 0)

        if not selected_files:
            QMessageBox.information(self, "Keine Auswahl", "Es wurden keine Duplikate zur Bereinigung markiert.")
            return

        dialog = DryRunSimulationDialog(self, selected_files, total_reclaimable)
        if dialog.exec() == QDialog.Accepted:
            use_recycle = dialog.chk_recycle.isChecked()
            deleted_count = 0
            fail_count = 0
            for f in selected_files:
                target_path = f["abs_path"]
                success = False
                if use_recycle:
                    success, _ = send_to_recycle_bin(target_path)
                else:
                    try:
                        os.remove(to_long_path(target_path))
                        success = True
                    except Exception:
                        success = False

                if success:
                    deleted_count += 1
                    self.db.log_operation("DELETE", target_path, size=f.get("size", 0))
                else:
                    fail_count += 1

            QMessageBox.information(
                self, "Bereinigung fertig",
                f"Ergebnis:\nErfolgreich entfernt: {deleted_count}\nFehlgeschlagen: {fail_count}\nFreigabe: {format_bytes(total_reclaimable)}"
            )
            self.start_scan()

