from typing import List, Dict, Any
from PySide6.QtCore import Qt, QPointF, QRectF, Signal
from PySide6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QGraphicsPathItem, QGraphicsTextItem, QGraphicsDropShadowEffect, QWidget
)
from PySide6.QtGui import (
    QPainter, QPen, QBrush, QColor, QFont, QPainterPath,
    QLinearGradient, QWheelEvent, QMouseEvent
)

from ...core.utils import format_bytes
from ...core.database import DatabaseManager
from ...core.drive_detector import DriveDetector
from ...core.plan import StoragePlan


class CanvasClusterNode(QGraphicsRectItem):
    def __init__(self, cluster: Dict[str, Any], pos: QPointF):
        super().__init__(0, 0, 200, 85)
        self.cluster = cluster
        self.setPos(pos)
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemSendsGeometryChanges)
        self.setBrush(QBrush(QColor("#1e293b")))
        self.setPen(QPen(QColor("#38bdf8"), 1.5))
        self.setAcceptHoverEvents(True)

        self.title_item = QGraphicsTextItem(self)
        self.title_item.setDefaultTextColor(QColor("#f8fafc"))
        self.title_item.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self.title_item.setPlainText(cluster.get("name", "Cluster")[:20])
        self.title_item.setPos(10, 8)

        self.sub_item = QGraphicsTextItem(self)
        self.sub_item.setDefaultTextColor(QColor("#94a3b8"))
        self.sub_item.setFont(QFont("Segoe UI", 8))
        self.sub_item.setPlainText(f"{cluster.get('file_count', 0):,} Files\n{format_bytes(cluster.get('total_size', 0))}")
        self.sub_item.setPos(10, 32)

    def get_output_anchor(self) -> QPointF:
        return self.mapToScene(QPointF(200, 42))



class CanvasDriveNode(QGraphicsRectItem):
    def __init__(self, drive: Dict[str, Any], pos: QPointF):
        super().__init__(0, 0, 240, 110)
        self.drive = drive
        self.setPos(pos)
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setBrush(QBrush(QColor("#0f172a")))
        self.setPen(QPen(QColor("#334155"), 2))

        self.title_item = QGraphicsTextItem(self)
        self.title_item.setDefaultTextColor(QColor("#38bdf8"))
        self.title_item.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.title_item.setPlainText(f"💽 {drive['letter']} [{drive['label']}]")
        self.title_item.setPos(10, 10)

        self.info_item = QGraphicsTextItem(self)
        self.info_item.setDefaultTextColor(QColor("#94a3b8"))
        self.info_item.setFont(QFont("Segoe UI", 9))
        self.info_item.setPlainText(
            f"Typ: {drive.get('drive_type', 'Fixed')} ({'SSD' if drive.get('is_ssd') else 'HDD'})\n"
            f"Frei: {format_bytes(drive['free_space'])} / {format_bytes(drive['total_space'])}"
        )
        self.info_item.setPos(10, 42)

    def get_input_anchor(self) -> QPointF:
        return self.mapToScene(QPointF(0, 55))



class CanvasBezierLink(QGraphicsPathItem):
    def __init__(self, source_node: CanvasClusterNode, target_node: CanvasDriveNode):
        super().__init__()
        self.source_node = source_node
        self.target_node = target_node
        pen = QPen(QColor("#38bdf8"), 2.5, Qt.DashLine)
        self.setPen(pen)
        self.update_path()

    def update_path(self) -> None:
        p1 = self.source_node.get_output_anchor()
        p2 = self.target_node.get_input_anchor()
        path = QPainterPath(p1)
        dx = max(60, abs(p2.x() - p1.x()) * 0.5)
        c1 = QPointF(p1.x() + dx, p1.y())
        c2 = QPointF(p2.x() - dx, p2.y())
        path.cubicTo(c1, c2, p2)
        self.setPath(path)



class PlanningCanvasView(QGraphicsView):
    sig_plan_changed = Signal()

    def __init__(self, db: DatabaseManager, plan: StoragePlan):
        self.scene = QGraphicsScene()
        super().__init__(self.scene)
        self.db = db
        self.plan = plan
        self.cluster_nodes: List[CanvasClusterNode] = []
        self.drive_nodes: List[CanvasDriveNode] = []
        self.links: List[CanvasBezierLink] = []

        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setStyleSheet("background-color: #0b1120; border: none;")
        self.setSceneRect(-1000, -1000, 3000, 3000)

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.15 if event.angleDelta().y() > 0 else 0.85
        self.scale(factor, factor)

    def populate_canvas(self, group_by: str = "category") -> None:
        self.scene.clear()
        self.cluster_nodes.clear()
        self.drive_nodes.clear()
        self.links.clear()

        volumes = self.db.get_volumes() or DriveDetector.get_mounted_drives()
        for idx, drv in enumerate(volumes):
            pos = QPointF(650, 100 + idx * 160)
            d_node = CanvasDriveNode(drv, pos)
            self.scene.addItem(d_node)
            self.drive_nodes.append(d_node)

        y_pos = 60
        for vol in volumes:
            clusters = self.db.get_volume_aggregates(vol["id"], group_by=group_by)
            for cl in clusters:
                pos = QPointF(100, y_pos)
                c_node = CanvasClusterNode(cl, pos)
                self.scene.addItem(c_node)
                self.cluster_nodes.append(c_node)
                y_pos += 110

        if self.cluster_nodes and self.drive_nodes:
            link = CanvasBezierLink(self.cluster_nodes[0], self.drive_nodes[-1])
            self.scene.addItem(link)
            self.links.append(link)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        super().mouseMoveEvent(event)
        for link in self.links:
            link.update_path()

