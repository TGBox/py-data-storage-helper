import platform
from PySide6.QtWidgets import QGroupBox
from PySide6.QtWidgets import QFrame
from PySide6.QtWidgets import QLineEdit
import os
from typing import List, Dict, Any, Optional
from PySide6.QtCore import Qt, Slot, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QSplitter, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox
)

from ...core.utils import format_bytes
from ...core.database import DatabaseManager
from ...core.drive_detector import DriveDetector
from ...core.plan import StoragePlan
from ..widgets.treemap_canvas import TreemapCanvasWidget


class StorageTreemapView(QWidget):
    sig_add_to_plan = Signal(dict)

    def __init__(self, db: DatabaseManager, plan: StoragePlan):
        super().__init__()
        self.db = db
        self.plan = plan
        self.current_volume_id: Optional[str] = None
        self.current_volume_letter: str = "C:\\"
        self.current_path: str = ""
        self.path_history: List[str] = []
        self.cached_children: List[Dict[str, Any]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header_bar = QHBoxLayout()
        title = QLabel("🗺️ Speicher-Treemap & Visueller Kapazitäts-Explorer (WinDirStat)")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f8fafc;")
        header_bar.addWidget(title)
        header_bar.addStretch()

        self.btn_up = QPushButton("⬆️ Ebene höher")
        self.btn_up.setProperty("class", "action-secondary")
        self.btn_up.clicked.connect(self.navigate_up)
        header_bar.addWidget(self.btn_up)

        self.btn_refresh = QPushButton("Aktualisieren")
        self.btn_refresh.setProperty("class", "action-secondary")
        self.btn_refresh.clicked.connect(self.reload_current_path)
        header_bar.addWidget(self.btn_refresh)
        layout.addLayout(header_bar)

        nav_bar = QHBoxLayout()
        self.combo_volume = QComboBox()
        self.combo_volume.setMinimumWidth(180)
        self.combo_volume.currentIndexChanged.connect(self.on_volume_changed)
        nav_bar.addWidget(self.combo_volume)

        self.txt_path_bar = QLineEdit()
        self.txt_path_bar.setReadOnly(True)
        self.txt_path_bar.setStyleSheet("background-color: #0f172a; color: #38bdf8; font-weight: 600;")
        nav_bar.addWidget(self.txt_path_bar, 1)

        self.combo_filter_size = QComboBox()
        self.combo_filter_size.addItem("Alle Größen anzeigen", 0)
        self.combo_filter_size.addItem("Nur > 1 MB", 1024 * 1024)
        self.combo_filter_size.addItem("Nur > 10 MB", 10 * 1024 * 1024)
        self.combo_filter_size.addItem("Nur > 100 MB", 100 * 1024 * 1024)
        self.combo_filter_size.addItem("Nur > 1 GB", 1024 * 1024 * 1024)
        self.combo_filter_size.currentIndexChanged.connect(self.apply_size_filter)
        nav_bar.addWidget(self.combo_filter_size)
        layout.addLayout(nav_bar)

        legend_frame = QFrame()
        legend_frame.setStyleSheet("background-color: #1e293b; border-radius: 6px; padding: 6px;")
        l_layout = QHBoxLayout(legend_frame)
        l_layout.setContentsMargins(10, 4, 10, 4)
        l_layout.setSpacing(16)

        legend_items = [
            ("🎬 Video", "#8b5cf6"), ("🖼️ Bild", "#38bdf8"), ("🎵 Audio", "#10b981"),
            ("📄 Dokument", "#f59e0b"), ("📦 Archiv", "#ef4444"), ("💻 Code", "#06b6d4"),
            ("📁 Ordner", "#475569")
        ]
        for name, color in legend_items:
            dot = QLabel(f"<span style='color:{color}; font-size:14px;'>■</span> {name}")
            dot.setStyleSheet("font-size: 11px; font-weight: 600; color: #cbd5e1;")
            l_layout.addWidget(dot)

        l_layout.addStretch()
        self.lbl_view_stats = QLabel("Bereit")
        self.lbl_view_stats.setStyleSheet("font-size: 11px; color: #94a3b8;")
        l_layout.addWidget(self.lbl_view_stats)
        layout.addWidget(legend_frame)

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setHandleWidth(8)

        self.canvas = TreemapCanvasWidget()
        self.canvas.sig_tile_hovered.connect(self.on_tile_hovered)
        self.canvas.sig_tile_selected.connect(self.on_tile_selected)
        self.canvas.sig_tile_double_clicked.connect(self.on_tile_double_clicked)
        self.splitter.addWidget(self.canvas)

        inspector_widget = QWidget()
        inspector_layout = QVBoxLayout(inspector_widget)
        inspector_layout.setContentsMargins(10, 0, 0, 0)
        inspector_layout.setSpacing(10)

        self.card_details = QGroupBox("🔍 Kachel-Inspektor")
        self.card_details.setStyleSheet("QGroupBox { background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 12px; font-weight: 600; color: #f8fafc; }")
        cd_layout = QVBoxLayout(self.card_details)
        cd_layout.setSpacing(6)

        self.lbl_sel_name = QLabel("Kein Element ausgewählt")
        self.lbl_sel_name.setStyleSheet("font-weight: 700; font-size: 13px; color: #38bdf8;")
        self.lbl_sel_name.setWordWrap(True)
        cd_layout.addWidget(self.lbl_sel_name)

        self.lbl_sel_info = QLabel("Klicken Sie auf eine Kachel in der Treemap, um Dateiinformationen anzuzeigen.")
        self.lbl_sel_info.setStyleSheet("color: #cbd5e1; font-size: 11px;")
        self.lbl_sel_info.setWordWrap(True)
        cd_layout.addWidget(self.lbl_sel_info)

        act_box = QHBoxLayout()
        self.btn_open_explorer = QPushButton("📂 In Explorer")
        self.btn_open_explorer.setProperty("class", "action-secondary")
        self.btn_open_explorer.setEnabled(False)
        self.btn_open_explorer.clicked.connect(self.open_selected_in_explorer)
        act_box.addWidget(self.btn_open_explorer)

        self.btn_plan_move = QPushButton("📋 In Transferplan")
        self.btn_plan_move.setProperty("class", "action-primary")
        self.btn_plan_move.setEnabled(False)
        self.btn_plan_move.clicked.connect(self.add_selected_to_plan)
        act_box.addWidget(self.btn_plan_move)
        cd_layout.addLayout(act_box)
        inspector_layout.addWidget(self.card_details)

        top_box = QGroupBox("🏆 Größte Elemente in dieser Ebene")
        top_box.setStyleSheet("QGroupBox { background-color: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 10px; font-weight: 600; color: #f8fafc; }")
        tb_layout = QVBoxLayout(top_box)
        self.table_top = QTableWidget()
        self.table_top.setColumnCount(3)
        self.table_top.setHorizontalHeaderLabels(["Name", "Größe", "Typ"])
        self.table_top.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table_top.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table_top.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table_top.verticalHeader().setVisible(False)
        self.table_top.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_top.itemSelectionChanged.connect(self.on_table_selection)
        tb_layout.addWidget(self.table_top)
        inspector_layout.addWidget(top_box, 1)

        self.splitter.addWidget(inspector_widget)
        self.splitter.setSizes([750, 320])
        layout.addWidget(self.splitter, 1)

    def refresh_volume_list(self) -> None:
        self.combo_volume.blockSignals(True)
        self.combo_volume.clear()
        volumes = self.db.get_volumes() or DriveDetector.get_mounted_drives()
        for vol in volumes:
            self.combo_volume.addItem(f"{vol['letter']} [{vol['label']}]", vol)
        self.combo_volume.blockSignals(False)
        if self.combo_volume.count() > 0:
            self.on_volume_changed()

    def on_volume_changed(self) -> None:
        vol_data = self.combo_volume.currentData()
        if not vol_data:
            return
        self.current_volume_id = vol_data["id"]
        self.current_volume_letter = vol_data.get("letter", "C:\\")
        self.current_path = ""
        self.path_history.clear()
        self.reload_current_path()

    def reload_current_path(self) -> None:
        if not self.current_volume_id:
            return
        disp_path = os.path.join(self.current_volume_letter, self.current_path).rstrip("\\") + "\\"
        self.txt_path_bar.setText(disp_path)
        self.btn_up.setEnabled(bool(self.current_path))
        children = self.db.get_treemap_node_children(self.current_volume_id, self.current_path)
        if not children and not self.current_path:
            children = self._generate_demo_treemap_data()
        self.cached_children = children
        self.apply_size_filter()

    def _generate_demo_treemap_data(self) -> List[Dict[str, Any]]:
        return [
            {"name": "Videos_RAW_4K", "path": "Videos_RAW_4K", "is_dir": True, "size": 340 * 1024**3, "file_count": 84, "category": "video"},
            {"name": "Steam_Library", "path": "Steam_Library", "is_dir": True, "size": 220 * 1024**3, "file_count": 34200, "category": "folder"},
            {"name": "Foto_Archiv_CR3", "path": "Foto_Archiv_CR3", "is_dir": True, "size": 115 * 1024**3, "file_count": 8200, "category": "image"},
            {"name": "Virtual_Disks_VMDK", "path": "Virtual_Disks_VMDK", "is_dir": True, "size": 75 * 1024**3, "file_count": 6, "category": "archive"},
            {"name": "Musik_Sammlung_FLAC", "path": "Musik_Sammlung_FLAC", "is_dir": True, "size": 32 * 1024**3, "file_count": 2400, "category": "audio"},
            {"name": "Entwickler_Repositories", "path": "Entwickler_Repositories", "is_dir": True, "size": 18 * 1024**3, "file_count": 65000, "category": "code"}
        ]

    def apply_size_filter(self) -> None:
        min_sz = self.combo_filter_size.currentData() or 0
        filtered = [c for c in self.cached_children if c.get("size", 0) >= min_sz]
        total_b = sum(c.get("size", 0) for c in filtered)
        self.lbl_view_stats.setText(f"{len(filtered)} Elemente | Gesamtsumme: {format_bytes(total_b)}")
        self.canvas.set_tiles_data(filtered)
        self.populate_top_table(filtered)

    def populate_top_table(self, items: List[Dict[str, Any]]) -> None:
        self.table_top.blockSignals(True)
        top15 = sorted(items, key=lambda x: x.get("size", 0), reverse=True)[:15]
        self.table_top.setRowCount(len(top15))
        for idx, item in enumerate(top15):
            icon = "📁 " if item.get("is_dir") else "📄 "
            name_item = QTableWidgetItem(icon + item.get("name", ""))
            name_item.setData(Qt.UserRole, item)
            self.table_top.setItem(idx, 0, name_item)
            self.table_top.setItem(idx, 1, QTableWidgetItem(format_bytes(item.get("size", 0))))
            self.table_top.setItem(idx, 2, QTableWidgetItem(item.get("category", "").capitalize()))
        self.table_top.blockSignals(False)

    def on_tile_hovered(self, tile: Dict[str, Any]) -> None:
        type_str = "Ordner" if tile.get("is_dir") else f"Datei ({tile.get('category', '').capitalize()})"
        self.lbl_view_stats.setText(f"Hover: {tile.get('name')} | {format_bytes(tile.get('size', 0))} [{type_str}]")

    def on_tile_selected(self, tile: Dict[str, Any]) -> None:
        self.lbl_sel_name.setText(("📁 " if tile.get("is_dir") else "📄 ") + tile.get("name", ""))
        full_p = os.path.join(self.current_volume_letter, tile.get("path", ""))
        info_lines = [
            f"<b>Größe:</b> {format_bytes(tile.get('size', 0))}",
            f"<b>Kategorie:</b> {tile.get('category', 'Unbekannt').capitalize()}",
            f"<b>Objekttyp:</b> {'Verzeichnis' if tile.get('is_dir') else 'Einzeldatei'}",
            f"<b>Pfad:</b> {full_p}"
        ]
        self.lbl_sel_info.setText("<br>".join(info_lines))
        self.btn_open_explorer.setEnabled(True)
        self.btn_plan_move.setEnabled(True)

    def on_tile_double_clicked(self, tile: Dict[str, Any]) -> None:
        if tile.get("is_dir"):
            self.path_history.append(self.current_path)
            self.current_path = tile.get("path", "")
            self.reload_current_path()

    def navigate_up(self) -> None:
        if not self.current_path:
            return
        if self.path_history:
            self.current_path = self.path_history.pop()
        else:
            norm = self.current_path.replace("/", "\\").rstrip("\\")
            self.current_path = norm.rsplit("\\", 1)[0] if "\\" in norm else ""
        self.reload_current_path()

    def on_table_selection(self) -> None:
        row = self.table_top.currentRow()
        if row >= 0:
            item = self.table_top.item(row, 0)
            if item:
                data = item.data(Qt.UserRole)
                if data:
                    self.canvas.selected_tile = data
                    self.canvas.update()
                    self.on_tile_selected(data)

    def open_selected_in_explorer(self) -> None:
        tile = self.canvas.selected_tile
        if not tile:
            return
        full_p = os.path.join(self.current_volume_letter, tile.get("path", ""))
        if platform.system() == "Windows":
            target = os.path.dirname(full_p) if not tile.get("is_dir") else full_p
            if os.path.exists(target):
                os.startfile(target)
            else:
                QMessageBox.information(self, "Explorer", f"Pfad:\n{full_p}")
        else:
            QMessageBox.information(self, "Explorer", f"Pfad:\n{full_p}")

    def add_selected_to_plan(self) -> None:
        tile = self.canvas.selected_tile
        if not tile:
            return
        self.plan.add_operation(
            op_type="MOVE",
            src_vol=self.current_volume_letter,
            src_path=tile.get("path", tile.get("name")),
            tgt_vol="E:",
            tgt_path=f"Konsolidierung/{tile.get('name')}",
            size=tile.get("size", 0)
        )
        QMessageBox.information(
            self, "Plan aktualisiert",
            f"'{tile.get('name')}' ({format_bytes(tile.get('size', 0))}) wurde in den Ausführungsplan aufgenommen."
        )

