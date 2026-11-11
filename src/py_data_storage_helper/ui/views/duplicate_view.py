from PySide6.QtWidgets import QDialog
import datetime
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHeaderView
import os
from typing import List, Dict, Any, Optional
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QComboBox, QSpinBox, QSplitter,
    QTreeWidget, QTreeWidgetItem, QMessageBox
)

from ...core.utils import to_long_path, format_bytes
from ...core.windows import send_to_recycle_bin, drive_has_recycle_bin
from ...core.database import DatabaseManager
from ...core.drive_detector import DriveDetector
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

        self.btn_dry_run = QPushButton("Bereinigung simulieren && ausführen...")
        self.btn_dry_run.setProperty("class", "action-danger")
        self.btn_dry_run.clicked.connect(self.open_simulation)
        auto_sel_bar.addWidget(self.btn_dry_run)
        layout.addLayout(auto_sel_bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Auswahl / Gruppe", "Größe", "Redundanz", "Änderungsdatum", "Pfad"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeToContents)
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

        is_fuzzy = grp.get("type") == "FUZZY"
        top_item = QTreeWidgetItem(self.tree)
        top_item.setData(0, Qt.UserRole, grp.get("type", "EXACT"))
        count_lbl = f"{len(files)} ähnliche Namen, Inhalt nicht geprüft" if is_fuzzy else f"{len(files)} Kopien"
        top_item.setText(0, f"📁 Gruppe {len(self.duplicate_groups)}: {rep_file['name']} ({count_lbl})")
        top_item.setText(1, format_bytes(grp["size"]))
        top_item.setText(2, format_bytes(grp["wasted_bytes"]))
        top_item.setExpanded(True)
        top_item.setForeground(0, QColor("#38bdf8"))

        for idx, f in enumerate(files):
            child = QTreeWidgetItem(top_item)
            child.setFlags(child.flags() | Qt.ItemIsUserCheckable)
            # Fuzzy-Treffer sind nur namensähnlich, daher nie automatisch zum Löschen vormerken.
            child.setCheckState(0, Qt.Checked if (idx > 0 and not is_fuzzy) else Qt.Unchecked)
            child.setText(0, f["name"])
            child.setText(1, format_bytes(f["size"]))
            if is_fuzzy:
                child.setText(2, "Ähnlicher Name")
            else:
                child.setText(2, "Duplikat" if idx > 0 else "Original (Behalten)")
            dt_str = datetime.datetime.fromtimestamp(f.get("mtime", 0)).strftime("%Y-%m-%d %H:%M")
            child.setText(3, dt_str)
            abs_p = f.get("abs_path") or os.path.join(f.get("volume_letter", ""), f.get("path", ""))
            child.setText(4, abs_p)
            child.setData(0, Qt.UserRole, f)

    @Slot(list, 'qint64')
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
            if group_item.data(0, Qt.UserRole) == "FUZZY":
                continue  # Smarte Vorauswahl gilt nur für byte-identische Gruppen
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
        fully_selected: List[str] = []

        for g_idx in range(root.childCount()):
            group_item = root.child(g_idx)
            checked_in_group = 0
            for c_idx in range(group_item.childCount()):
                child = group_item.child(c_idx)
                if child.checkState(0) == Qt.Checked:
                    checked_in_group += 1
                    f_data = child.data(0, Qt.UserRole)
                    if f_data:
                        f_data["abs_path"] = child.text(4)
                        selected_files.append(f_data)
                        total_reclaimable += f_data.get("size", 0)
            if group_item.childCount() > 0 and checked_in_group == group_item.childCount():
                fully_selected.append(group_item.text(0))

        if not selected_files:
            QMessageBox.information(self, "Keine Auswahl", "Es wurden keine Duplikate zur Bereinigung markiert.")
            return

        if fully_selected:
            shown = "\n".join(fully_selected[:10])
            more = f"\n… und {len(fully_selected) - 10} weitere" if len(fully_selected) > 10 else ""
            QMessageBox.warning(
                self, "Bereinigung blockiert",
                "In diesen Gruppen sind alle Dateien zum Löschen markiert. "
                "Pro Gruppe muss mindestens eine Datei erhalten bleiben:\n\n" + shown + more
            )
            return

        dialog = DryRunSimulationDialog(self, selected_files, total_reclaimable)
        if dialog.exec() != QDialog.Accepted:
            return

        use_recycle = dialog.chk_recycle.isChecked()
        skipped_count = 0
        permanent_paths = set()

        if use_recycle:
            # Auf Laufwerken ohne Papierkorb würde Windows stillschweigend endgültig löschen.
            no_bin = [f for f in selected_files if not drive_has_recycle_bin(f["abs_path"])]
            if no_bin:
                drives = sorted({os.path.splitdrive(f["abs_path"])[0] or f["abs_path"] for f in no_bin})
                no_bin_bytes = sum(f.get("size", 0) for f in no_bin)
                box = QMessageBox(self)
                box.setIcon(QMessageBox.Warning)
                box.setWindowTitle("Kein Papierkorb verfügbar")
                box.setText(
                    f"{len(no_bin)} von {len(selected_files)} Dateien ({format_bytes(no_bin_bytes)}) liegen auf "
                    f"Laufwerken ohne Papierkorb: {', '.join(drives)}.\n\n"
                    "Diese Dateien können nur endgültig gelöscht werden."
                )
                btn_delete = box.addButton("Endgültig löschen", QMessageBox.DestructiveRole)
                btn_skip = box.addButton("Diese Dateien überspringen", QMessageBox.AcceptRole)
                box.addButton("Abbrechen", QMessageBox.RejectRole)
                box.setDefaultButton(btn_skip)
                box.exec()
                clicked = box.clickedButton()
                no_bin_paths = {f["abs_path"] for f in no_bin}
                if clicked == btn_delete:
                    permanent_paths = no_bin_paths
                elif clicked == btn_skip:
                    skipped_count = len(no_bin)
                    selected_files = [f for f in selected_files if f["abs_path"] not in no_bin_paths]
                else:
                    return

        # Zwischen Scan und Bereinigung kann sich die Laufwerkszuordnung geändert haben.
        mounted = {d["id"]: d["letter"] for d in DriveDetector.get_mounted_drives()}
        deleted_count = 0
        fail_count = 0
        freed_bytes = 0
        deleted_ids: List[int] = []
        for f in selected_files:
            target_path = f["abs_path"]
            letter = mounted.get(f.get("volume_id"))
            if not letter or not target_path.upper().startswith(letter.upper()):
                fail_count += 1
                continue

            success = False
            if use_recycle and target_path not in permanent_paths:
                success, _ = send_to_recycle_bin(target_path)
            else:
                try:
                    os.remove(to_long_path(target_path))
                    success = True
                except Exception:
                    success = False

            if success:
                deleted_count += 1
                freed_bytes += f.get("size", 0)
                if f.get("id") is not None:
                    deleted_ids.append(f["id"])
                self.db.log_operation("DELETE", target_path, size=f.get("size", 0))
            else:
                fail_count += 1

        self.db.delete_file_records(deleted_ids)  # Index nachführen

        QMessageBox.information(
            self, "Bereinigung fertig",
            f"Ergebnis:\nErfolgreich entfernt: {deleted_count}\nÜbersprungen (kein Papierkorb): {skipped_count}\n"
            f"Fehlgeschlagen: {fail_count}\nFreigabe: {format_bytes(freed_bytes)}"
        )
        self.start_scan()
