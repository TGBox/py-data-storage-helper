from PySide6.QtWidgets import QScrollArea
from typing import Any
from PySide6.QtWidgets import QVBoxLayout
from typing import Dict
from typing import Optional
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QHBoxLayout

from ...core.database import DatabaseManager
from ...core.drive_detector import DriveDetector
from ...core.plan import StoragePlan
from ..widgets.kanban_widgets import KanbanColumnWidget


class PlanningKanbanView(QWidget):
    sig_plan_updated = Signal()

    def __init__(self, db: DatabaseManager, plan: StoragePlan):
        super().__init__()
        self.db = db
        self.plan = plan
        self.columns: Dict[str, KanbanColumnWidget] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.board_widget = QWidget()
        self.board_layout = QHBoxLayout(self.board_widget)
        self.board_layout.setContentsMargins(10, 10, 10, 10)
        self.board_layout.setSpacing(12)
        scroll.setWidget(self.board_widget)
        layout.addWidget(scroll)

    def refresh_columns(self, group_by: str = "category") -> None:
        while self.board_layout.count() > 0:
            item = self.board_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self.columns.clear()

        pool_dummy = {"id": "POOL", "label": "Pool", "letter": "", "total_space": 0, "free_space": 0, "is_ssd": 0}
        pool_col = KanbanColumnWidget(pool_dummy, is_pool=True)
        pool_col.sig_cluster_assigned.connect(self.on_cluster_assigned)
        self.board_layout.addWidget(pool_col)
        self.columns["POOL"] = pool_col

        volumes = self.db.get_volumes() or DriveDetector.get_mounted_drives()
        for vol in volumes:
            col = KanbanColumnWidget(vol, is_pool=False)
            col.sig_cluster_assigned.connect(self.on_cluster_assigned)
            self.board_layout.addWidget(col)
            self.columns[vol["id"]] = col

        self.board_layout.addStretch()

        for vol in volumes:
            clusters = self.db.get_volume_aggregates(vol["id"], group_by=group_by)
            for cl in clusters:
                pool_col.add_card(cl)

        self.board_layout.activate()
        self.board_widget.adjustSize()

    def on_cluster_assigned(self, cluster: Dict[str, Any], target_drive_id: Optional[str]) -> None:
        if not target_drive_id:
            return
        volumes = self.db.get_volumes()
        vol = next((v for v in volumes if v["id"] == target_drive_id), None)
        src = next((v for v in volumes if v["id"] == cluster.get("volume_id")), None)
        if not vol or not src or vol["id"] == src["id"]:
            return  # unbekanntes Laufwerk oder Quelle = Ziel
        target_letter = vol["letter"]

        group_by = cluster.get("group_by", "category")
        group_name = cluster.get("group_name")
        if not group_name:
            return

        if group_by == "category":
            # Verstreute Dateien einer Kategorie: Ordnerstruktur bleibt unter Konsolidierung\<Kategorie>\ erhalten.
            files = self.db.get_cluster_file_paths(src["id"], "category", group_name)
            src_path, tgt_path = "", f"Konsolidierung\\{group_name}"
        elif group_name == "[Root Files]":
            files = self.db.get_cluster_file_paths(src["id"], "folder", group_name)
            src_path, tgt_path = "", "Konsolidierung"
        else:
            # Hauptordner: wird als ganzer Ordner übertragen.
            files = None
            src_path, tgt_path = group_name, f"Konsolidierung\\{group_name}"

        if files is not None and not files:
            return

        self.plan.add_operation(
            op_type="MOVE",
            src_vol=src["letter"],
            src_path=src_path,
            tgt_vol=target_letter,
            tgt_path=tgt_path,
            size=cluster.get("total_size", 0),
            files=files
        )
        if target_drive_id in self.columns:
            self.columns[target_drive_id].add_card(cluster)
        self.sig_plan_updated.emit()

