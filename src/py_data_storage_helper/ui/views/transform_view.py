from PySide6.QtGui import QColor
import datetime
from PySide6.QtWidgets import QCheckBox
from PySide6.QtWidgets import QGroupBox
import os
import re
from typing import List, Dict, Any
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox
)

from ...core.utils import to_long_path
from ...core.database import DatabaseManager
from ...core.drive_detector import DriveDetector


class BatchTransformView(QWidget):
    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db
        self.loaded_files: List[Dict[str, Any]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Batch-Transformation & Umbenennungs-Manager")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f8fafc;")
        layout.addWidget(title)

        filter_bar = QHBoxLayout()
        self.combo_volume = QComboBox()
        self.combo_volume.addItem("Alle Laufwerke", None)
        filter_bar.addWidget(self.combo_volume)

        self.combo_category = QComboBox()
        self.combo_category.addItems(["Alle Kategorien", "image", "video", "audio", "document", "archive", "code", "other"])
        filter_bar.addWidget(self.combo_category)

        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText("Filter für Batch-Dateien (z.B. .mp4, IMG)...")
        filter_bar.addWidget(self.txt_filter, 1)

        btn_load = QPushButton("Dateien laden")
        btn_load.setProperty("class", "action-primary")
        btn_load.clicked.connect(self.load_files)
        filter_bar.addWidget(btn_load)
        layout.addLayout(filter_bar)

        rules_box = QGroupBox("Transformations-Regeln")
        r_layout = QVBoxLayout(rules_box)

        r_row1 = QHBoxLayout()
        self.txt_prefix = QLineEdit()
        self.txt_prefix.setPlaceholderText("Präfix hinzufügen (z.B. Archiv_2026_)")
        self.txt_prefix.textChanged.connect(self.update_preview)
        r_row1.addWidget(self.txt_prefix)

        self.txt_suffix = QLineEdit()
        self.txt_suffix.setPlaceholderText("Suffix hinzufügen (z.B. _final)")
        self.txt_suffix.textChanged.connect(self.update_preview)
        r_row1.addWidget(self.txt_suffix)
        r_layout.addLayout(r_row1)

        r_row2 = QHBoxLayout()
        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Suchen...")
        self.txt_search.textChanged.connect(self.update_preview)
        r_row2.addWidget(self.txt_search)

        self.txt_replace = QLineEdit()
        self.txt_replace.setPlaceholderText("Ersetzen durch...")
        self.txt_replace.textChanged.connect(self.update_preview)
        r_row2.addWidget(self.txt_replace)

        self.chk_add_date = QCheckBox("Datum voranstellen (YYYY-MM-DD)")
        self.chk_add_date.stateChanged.connect(self.update_preview)
        r_row2.addWidget(self.chk_add_date)
        r_layout.addLayout(r_row2)
        layout.addWidget(rules_box)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Original-Name", "Neuer Name (Vorschau)", "Status / Kollision", "Verzeichnis"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        layout.addWidget(self.table)

        btn_exec_bar = QHBoxLayout()
        self.lbl_stats = QLabel("Keine Dateien geladen.")
        self.lbl_stats.setStyleSheet("color: #94a3b8; font-size: 12px;")
        btn_exec_bar.addWidget(self.lbl_stats)
        btn_exec_bar.addStretch()

        self.btn_execute = QPushButton("Batch-Umbenennung verbindlich ausführen")
        self.btn_execute.setProperty("class", "action-primary")
        self.btn_execute.setEnabled(False)
        self.btn_execute.clicked.connect(self.execute_batch)
        btn_exec_bar.addWidget(self.btn_execute)
        layout.addLayout(btn_exec_bar)

    def refresh_volume_list(self) -> None:
        self.combo_volume.clear()
        self.combo_volume.addItem("Alle Laufwerke", None)
        for vol in self.db.get_volumes():
            self.combo_volume.addItem(f"{vol['letter']} [{vol['label']}]", vol["id"])

    def load_files(self) -> None:
        vol_id = self.combo_volume.currentData()
        cat = self.combo_category.currentText()
        search_txt = self.txt_filter.text().strip()

        with self.db.get_connection() as conn:
            query = "SELECT f.*, v.letter as volume_letter FROM files f JOIN volumes v ON f.volume_id = v.id WHERE 1=1"
            params: List[Any] = []
            if vol_id:
                query += " AND f.volume_id = ?"
                params.append(vol_id)
            if cat and cat != "Alle Kategorien":
                query += " AND f.category = ?"
                params.append(cat.lower())
            if search_txt:
                query += " AND (f.name LIKE ? OR f.path LIKE ?)"
                params.append(f"%{search_txt}%")
                params.append(f"%{search_txt}%")
            query += " ORDER BY f.name ASC LIMIT 500"
            rows = conn.execute(query, params).fetchall()
            # Nur Dateien von aktuell eingebundenen Volumes, mit deren jetzigem Buchstaben.
            mounted = {d["id"]: d["letter"] for d in DriveDetector.get_mounted_drives()}
            self.loaded_files = []
            for r in rows:
                if r["volume_id"] in mounted:
                    f = dict(r)
                    f["volume_letter"] = mounted[r["volume_id"]]
                    self.loaded_files.append(f)

        self.update_preview()

    def update_preview(self) -> None:
        prefix = self.txt_prefix.text()
        suffix = self.txt_suffix.text()
        search_term = self.txt_search.text()
        replace_term = self.txt_replace.text()
        add_date = self.chk_add_date.isChecked()

        self.table.setRowCount(len(self.loaded_files))
        planned_names = set()
        has_changes = False

        for row, f in enumerate(self.loaded_files):
            orig_name = f["name"]
            stem, ext = os.path.splitext(orig_name)
            new_stem = stem

            if search_term:
                new_stem = new_stem.replace(search_term, replace_term)
            if prefix:
                new_stem = prefix + new_stem
            if suffix:
                new_stem = new_stem + suffix
            if add_date:
                dt_prefix = datetime.datetime.fromtimestamp(f.get("mtime", 0)).strftime("%Y-%m-%d_")
                new_stem = dt_prefix + new_stem

            new_name = new_stem + ext
            f["planned_name"] = new_name

            self.table.setItem(row, 0, QTableWidgetItem(orig_name))
            new_item = QTableWidgetItem(new_name)
            new_item.setForeground(QColor("#38bdf8" if new_name != orig_name else "#94a3b8"))
            self.table.setItem(row, 1, new_item)

            status_item = QTableWidgetItem()
            if new_name == orig_name:
                status_item.setText("Keine Änderung")
                status_item.setForeground(QColor("#64748b"))
            elif new_name in planned_names:
                status_item.setText("⚠️ Kollision!")
                status_item.setForeground(QColor("#ef4444"))
            else:
                status_item.setText("Bereit")
                status_item.setForeground(QColor("#10b981"))
                has_changes = True

            planned_names.add(new_name)
            self.table.setItem(row, 2, status_item)
            self.table.setItem(row, 3, QTableWidgetItem(f.get("path", "")))

        self.btn_execute.setEnabled(has_changes)
        self.lbl_stats.setText(f"{len(self.loaded_files)} Dateien geladen. Bereit für Transformation.")

    def execute_batch(self) -> None:
        confirm = QMessageBox.question(
            self, "Transformation bestätigen",
            f"Möchten Sie die Umbenennung für {len(self.loaded_files)} Dateien wirklich ausführen?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm != QMessageBox.Yes:
            return

        success_count = 0
        error_count = 0
        for f in self.loaded_files:
            orig_name = f["name"]
            new_name = f.get("planned_name")
            if not new_name or new_name == orig_name:
                continue

            vol_letter = f["volume_letter"]
            old_full_path = os.path.join(vol_letter, f["path"])
            dir_name = os.path.dirname(old_full_path)
            new_full_path = os.path.join(dir_name, new_name)

            try:
                os.rename(to_long_path(old_full_path), to_long_path(new_full_path))
                new_rel_path = os.path.relpath(new_full_path, vol_letter)
                with self.db.get_connection() as conn:
                    conn.execute("UPDATE files SET name = ?, path = ? WHERE id = ?", (new_name, new_rel_path, f["id"]))
                    conn.commit()
                self.db.log_operation("RENAME", old_full_path, new_full_path, size=f.get("size", 0))
                success_count += 1
            except Exception:
                error_count += 1

        QMessageBox.information(
            self, "Batch-Vorgang beendet",
            f"Erfolgreich umbenannt: {success_count}\nFehlerhaft: {error_count}"
        )
        self.load_files()

