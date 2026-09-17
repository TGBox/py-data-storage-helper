from typing import Optional
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QStackedWidget

from ...core.database import DatabaseManager
from ...core.plan import StoragePlan
from ..widgets.canvas_nodes import PlanningCanvasView
from .kanban_view import PlanningKanbanView


class VisualPlanningView(QWidget):
    """Dual visual planning hub integrating both Kanban columns and Node-Canvas views."""
    sig_plan_updated = Signal()

    def __init__(self, db: DatabaseManager, plan: StoragePlan):
        super().__init__()
        self.db = db
        self.plan = plan

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("🎨 Visuelle Speicherplanung & Datenverteilung")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #f8fafc;")
        header.addWidget(title)
        header.addStretch()

        self.combo_group = QComboBox()
        self.combo_group.addItem("Nach Dateikategorie aggregieren", "category")
        self.combo_group.addItem("Nach Hauptordner aggregieren", "folder")
        self.combo_group.currentIndexChanged.connect(self.refresh_visuals)
        header.addWidget(self.combo_group)

        self.btn_view_kanban = QPushButton("📋 Kanban-Board")
        self.btn_view_kanban.setProperty("class", "action-primary")
        self.btn_view_kanban.clicked.connect(lambda: self.switch_view_mode(0))
        header.addWidget(self.btn_view_kanban)

        self.btn_view_canvas = QPushButton("🕸️ Node-Canvas")
        self.btn_view_canvas.setProperty("class", "action-secondary")
        self.btn_view_canvas.clicked.connect(lambda: self.switch_view_mode(1))
        header.addWidget(self.btn_view_canvas)

        layout.addLayout(header)

        self.stack = QStackedWidget()
        self.kanban_view = PlanningKanbanView(self.db, self.plan)
        self.kanban_view.sig_plan_updated.connect(self.sig_plan_updated.emit)

        self.canvas_view = PlanningCanvasView(self.db, self.plan)
        self.stack.addWidget(self.kanban_view)
        self.stack.addWidget(self.canvas_view)
        layout.addWidget(self.stack, 1)

    def switch_view_mode(self, idx: int) -> None:
        self.stack.setCurrentIndex(idx)
        self.btn_view_kanban.setProperty("class", "action-primary" if idx == 0 else "action-secondary")
        self.btn_view_canvas.setProperty("class", "action-primary" if idx == 1 else "action-secondary")
        self.btn_view_kanban.style().polish(self.btn_view_kanban)
        self.btn_view_canvas.style().polish(self.btn_view_canvas)
        self.refresh_visuals()

    def refresh_visuals(self) -> None:
        grp = self.combo_group.currentData() or "category"
        if self.stack.currentIndex() == 0:
            self.kanban_view.refresh_columns(grp)
        else:
            self.canvas_view.populate_canvas(grp)

