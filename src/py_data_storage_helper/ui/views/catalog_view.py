from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QComboBox, QTableWidget, QTableWidgetItem, QHeaderView
)

from ...core.utils import format_bytes
from ...core.database import DatabaseManager


class CatalogExplorerView(QWidget):
    def __init__(self, db: DatabaseManager):
        super().__init__()
        self.db = db

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        title = QLabel("Katalog & Offline Datei-Explorer")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f8fafc;")
        layout.addWidget(title)

        filter_bar = QHBoxLayout()
        self.combo_volume = QComboBox()
        self.combo_volume.addItem("Alle erfassten Laufwerke", None)
        self.combo_volume.currentIndexChanged.connect(self.apply_search)
        filter_bar.addWidget(self.combo_volume)

        self.combo_category = QComboBox()
        self.combo_category.addItems(["Alle Kategorien", "image", "video", "audio", "document", "archive", "code", "other"])
        self.combo_category.currentIndexChanged.connect(self.apply_search)
        filter_bar.addWidget(self.combo_category)

        self.txt_search = QLineEdit()
        self.txt_search.setPlaceholderText("Dateiname oder Endung filtern...")
        self.txt_search.returnPressed.connect(self.apply_search)
        filter_bar.addWidget(self.txt_search, 1)

        btn_search = QPushButton("Suchen")
        btn_search.setProperty("class", "action-primary")
        btn_search.clicked.connect(self.apply_search)
        filter_bar.addWidget(btn_search)
        layout.addLayout(filter_bar)

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Name", "Größe", "Kategorie", "Änderungsdatum", "Relativer Pfad"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.table)

        self.lbl_summary = QLabel("Keine Dateien geladen.")
        self.lbl_summary.setStyleSheet("color: #94a3b8; font-size: 12px;")
        layout.addWidget(self.lbl_summary)

    def refresh_volume_list(self) -> None:
        self.combo_volume.clear()
        self.combo_volume.addItem("Alle erfassten Laufwerke", None)
        for vol in self.db.get_volumes():
            self.combo_volume.addItem(f"{vol['letter']} [{vol['label']}]", vol["id"])

    def apply_search(self) -> None:
        vol_id = self.combo_volume.currentData()
        cat = self.combo_category.currentText()
        if cat == "Alle Kategorien":
            cat = None
        search_txt = self.txt_search.text().strip()

        with self.db.get_connection() as conn:
            query = "SELECT name, size, category, mtime, path FROM files WHERE 1=1"
            params = []
            if vol_id:
                query += " AND volume_id = ?"
                params.append(vol_id)
            if cat:
                query += " AND category = ?"
                params.append(cat)
            if search_txt:
                query += " AND (name LIKE ? OR path LIKE ?)"
                params.append(f"%{search_txt}%")
                params.append(f"%{search_txt}%")
            query += " ORDER BY size DESC LIMIT 1000"
            rows = conn.execute(query, params).fetchall()

        self.table.setRowCount(len(rows))
        total_sz = 0
        for idx, row in enumerate(rows):
            sz = row["size"]
            total_sz += sz
            dt_str = datetime.datetime.fromtimestamp(row["mtime"]).strftime("%Y-%m-%d %H:%M")
            self.table.setItem(idx, 0, QTableWidgetItem(row["name"]))
            self.table.setItem(idx, 1, QTableWidgetItem(format_bytes(sz)))
            self.table.setItem(idx, 2, QTableWidgetItem(row["category"].capitalize()))
            self.table.setItem(idx, 3, QTableWidgetItem(dt_str))
            self.table.setItem(idx, 4, QTableWidgetItem(row["path"]))

        self.lbl_summary.setText(f"{len(rows):,} Einträge angezeigt (Summe: {format_bytes(total_sz)}).")

