import json
from typing import List
from PySide6.QtGui import QMouseEvent
import math
from typing import Dict, Any
from PySide6.QtCore import Qt, Signal, QMimeData, QPoint
from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QProgressBar, QScrollArea, QWidget, QApplication
)
from PySide6.QtGui import QDrag

from ...core.utils import format_bytes


class KanbanCardWidget(QFrame):
    def __init__(self, cluster_data: Dict[str, Any]):
        super().__init__()
        self.cluster_data = cluster_data
        self.setObjectName("KanbanCard")
        self.setStyleSheet("""
            QFrame#KanbanCard {
                background-color: #1e293b;
                border: 1px solid #334155;
                border-radius: 8px;
                padding: 10px;
                margin-bottom: 6px;
            }
            QFrame#KanbanCard:hover {
                border: 1px solid #38bdf8;
                background-color: #243248;
            }
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        icon_lbl = QLabel("📦")
        title_lbl = QLabel(cluster_data.get("name", "Cluster"))
        title_lbl.setStyleSheet("font-weight: 700; color: #f8fafc; font-size: 13px;")
        top_row.addWidget(icon_lbl)
        top_row.addWidget(title_lbl, 1)
        layout.addLayout(top_row)

        details_lbl = QLabel(
            f"{cluster_data.get('file_count', 0):,} Dateien | "
            f"<b style='color:#38bdf8;'>{format_bytes(cluster_data.get('total_size', 0))}</b>"
        )
        details_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
        layout.addWidget(details_lbl)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            drag = QDrag(self)
            mime = QMimeData()
            mime.setText(json.dumps(self.cluster_data))
            drag.setMimeData(mime)
            drag.exec(Qt.MoveAction)
        super().mousePressEvent(event)



class KanbanColumnWidget(QFrame):
    sig_cluster_assigned = Signal(dict, str)

    def __init__(self, drive_data: Dict[str, Any], is_pool: bool = False):
        super().__init__()
        self.drive_data = drive_data
        self.is_pool = is_pool
        self.assigned_clusters: List[Dict[str, Any]] = []
        self.setAcceptDrops(True)
        self.setMinimumWidth(260)
        self.setStyleSheet("QFrame { background-color: #0f172a; border: 1px solid #334155; border-radius: 10px; }")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 12, 10, 12)
        layout.setSpacing(8)

        header = QHBoxLayout()
        drv_name = "Quell-Pool (Nicht zugewiesen)" if is_pool else f"{drive_data['letter']} {drive_data['label']}"
        lbl_name = QLabel(drv_name)
        lbl_name.setStyleSheet("font-weight: 700; font-size: 14px; color: #f8fafc;")
        header.addWidget(lbl_name)
        header.addStretch()

        type_badge = QLabel("POOL" if is_pool else ("SSD" if drive_data.get("is_ssd") else "HDD"))
        type_badge.setStyleSheet("background-color: #2563eb; color: #fff; padding: 2px 6px; border-radius: 4px; font-size: 10px;")
        header.addWidget(type_badge)
        layout.addLayout(header)

        if not is_pool:
            self.lbl_space = QLabel()
            self.lbl_space.setStyleSheet("font-size: 11px; color: #94a3b8;")
            self.bar_space = QProgressBar()
            self.bar_space.setFixedHeight(8)
            layout.addWidget(self.lbl_space)
            layout.addWidget(self.bar_space)
            self.update_space_display()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("background: transparent; border: none;")
        self.card_container = QWidget()
        self.card_container.setStyleSheet("background: transparent;")
        self.card_layout = QVBoxLayout(self.card_container)
        self.card_layout.setContentsMargins(2, 2, 2, 2)
        self.card_layout.setSpacing(6)
        self.card_layout.addStretch()
        scroll.setWidget(self.card_container)
        layout.addWidget(scroll, 1)

    def add_card(self, cluster: Dict[str, Any]) -> None:
        self.assigned_clusters.append(cluster)
        card = KanbanCardWidget(cluster)
        self.card_layout.insertWidget(self.card_layout.count() - 1, card)
        if not self.is_pool:
            self.update_space_display()

    def clear_cards(self) -> None:
        self.assigned_clusters.clear()
        while self.card_layout.count() > 1:
            item = self.card_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self.is_pool:
            self.update_space_display()

    def update_space_display(self) -> None:
        total = self.drive_data["total_space"]
        free = self.drive_data["free_space"]
        assigned_bytes = sum(c.get("total_size", 0) for c in self.assigned_clusters)
        projected_free = free - assigned_bytes
        used = total - free + assigned_bytes
        pct = min(100, int((used / total * 100))) if total > 0 else 0

        self.bar_space.setValue(pct)
        if projected_free < 0:
            self.lbl_space.setText(f"<b style='color:#ef4444;'>⚠️ Überlauf! {format_bytes(abs(projected_free))} zu wenig</b>")
            self.bar_space.setStyleSheet("QProgressBar::chunk { background-color: #ef4444; }")
        else:
            color = "#10b981" if pct < 80 else "#f59e0b"
            self.lbl_space.setText(f"Frei: <b>{format_bytes(projected_free)}</b> ({pct}% belegt)")
            self.bar_space.setStyleSheet(f"QProgressBar::chunk {{ background-color: {color}; }}")

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasText():
            event.acceptProposedAction()
            self.setStyleSheet("QFrame { background-color: #1e293b; border: 2px dashed #38bdf8; border-radius: 10px; }")

    def dragLeaveEvent(self, event) -> None:
        self.setStyleSheet("QFrame { background-color: #0f172a; border: 1px solid #334155; border-radius: 10px; }")

    def dropEvent(self, event) -> None:
        self.setStyleSheet("QFrame { background-color: #0f172a; border: 1px solid #334155; border-radius: 10px; }")
        try:
            cluster_data = json.loads(event.mimeData().text())
            target_id = None if self.is_pool else self.drive_data["id"]
            self.sig_cluster_assigned.emit(cluster_data, target_id)
            event.acceptProposedAction()
        except Exception as ex:
            print(f"Drop error: {ex}")

