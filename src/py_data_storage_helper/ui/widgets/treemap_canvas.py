from typing import List, Dict, Any, Optional
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QBrush,
    QLinearGradient, QMouseEvent
)

from ...core.utils import format_bytes


class SquarifiedTreemapEngine:
    @classmethod
    def calculate_layout(cls, items: List[Dict[str, Any]], bounds: QRectF) -> List[Dict[str, Any]]:
        if not items or bounds.width() <= 0 or bounds.height() <= 0:
            return []

        valid_items = [dict(item) for item in items if item.get("size", 0) > 0]
        if not valid_items:
            return []

        valid_items.sort(key=lambda x: x["size"], reverse=True)
        total_size = sum(x["size"] for x in valid_items)
        if total_size <= 0:
            return []

        total_area = bounds.width() * bounds.height()
        for item in valid_items:
            item["area"] = (item["size"] / total_size) * total_area

        results: List[Dict[str, Any]] = []
        cls._squarify(valid_items, bounds, results)
        return results

    @classmethod
    def _squarify(cls, children: List[Dict[str, Any]], *args) -> None:
        """
        Iterative squarified treemap layout to prevent recursion depth exhaustion.
        Supports both _squarify(children, rect, results) and legacy _squarify(children, current_row, rect, results).
        """
        if len(args) == 2:
            rect, results = args
        elif len(args) == 3:
            _, rect, results = args
        else:
            raise TypeError("Invalid arguments to _squarify")

        current_row: List[Dict[str, Any]] = []
        current_worst = float('inf')
        i = 0
        n = len(children)

        while i < n:
            side = min(rect.width(), rect.height())
            if side <= 0.0001:
                break

            c = children[i]
            if c.get("area", 0) <= 0:
                c["rect"] = QRectF(rect.x(), rect.y(), 0.0, 0.0)
                results.append(c)
                i += 1
                continue

            row_with_c = current_row + [c]
            new_worst = cls._worst_ratio(row_with_c, rect)

            if not current_row or current_worst >= new_worst:
                current_row.append(c)
                current_worst = new_worst
                i += 1
            else:
                rect = cls._layout_row(current_row, rect, results)
                current_row = []
                current_worst = float('inf')

        if current_row:
            cls._layout_row(current_row, rect, results)

        while i < n:
            children[i]["rect"] = QRectF(rect.x(), rect.y(), 0.0, 0.0)
            results.append(children[i])
            i += 1

    @classmethod
    def _worst_ratio(cls, row: List[Dict[str, Any]], rect: QRectF) -> float:
        row_area = sum(item["area"] for item in row)
        if row_area <= 0:
            return float('inf')
        side = min(rect.width(), rect.height())
        if side <= 0:
            return float('inf')

        side_sq = side * side
        max_a = max(item["area"] for item in row)
        min_a = min(item["area"] for item in row)
        if min_a <= 0:
            return float('inf')
        ratio1 = (side_sq * max_a) / (row_area * row_area)
        ratio2 = (row_area * row_area) / (side_sq * min_a)
        return max(ratio1, ratio2)

    @classmethod
    def _layout_row(cls, row: List[Dict[str, Any]], rect: QRectF, results: List[Dict[str, Any]]) -> QRectF:
        row_area = sum(item["area"] for item in row)
        if row_area <= 0:
            return rect

        is_horizontal = rect.width() >= rect.height()
        if is_horizontal:
            row_width = row_area / rect.height() if rect.height() > 0 else 0
            cur_y = rect.y()
            for item in row:
                h = item["area"] / row_width if row_width > 0 else 0
                item["rect"] = QRectF(rect.x(), cur_y, row_width, h)
                results.append(item)
                cur_y += h
            return QRectF(rect.x() + row_width, rect.y(), max(0.0, rect.width() - row_width), rect.height())
        else:
            row_height = row_area / rect.width() if rect.width() > 0 else 0
            cur_x = rect.x()
            for item in row:
                w = item["area"] / row_height if row_height > 0 else 0
                item["rect"] = QRectF(cur_x, rect.y(), w, row_height)
                results.append(item)
                cur_x += w
            return QRectF(rect.x(), rect.y() + row_height, rect.width(), max(0.0, rect.height() - row_height))



class TreemapCanvasWidget(QWidget):
    sig_tile_hovered = Signal(dict)
    sig_tile_selected = Signal(dict)
    sig_tile_double_clicked = Signal(dict)

    CATEGORY_COLORS = {
        "video": QColor("#8b5cf6"),
        "image": QColor("#38bdf8"),
        "audio": QColor("#10b981"),
        "document": QColor("#f59e0b"),
        "archive": QColor("#ef4444"),
        "code": QColor("#06b6d4"),
        "folder": QColor("#334155"),
        "other": QColor("#64748b")
    }

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(450, 320)
        self.tiles: List[Dict[str, Any]] = []
        self.hovered_tile: Optional[Dict[str, Any]] = None
        self.selected_tile: Optional[Dict[str, Any]] = None

    def set_tiles_data(self, raw_items: List[Dict[str, Any]]) -> None:
        w = max(10, self.width())
        h = max(10, self.height())
        bounds = QRectF(2, 2, w - 4, h - 4)
        self.tiles = SquarifiedTreemapEngine.calculate_layout(raw_items, bounds)
        self.hovered_tile = None
        self.selected_tile = None
        self.update()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.tiles:
            items_copy = [dict(t) for t in self.tiles]
            w = max(10, self.width())
            h = max(10, self.height())
            bounds = QRectF(2, 2, w - 4, h - 4)
            self.tiles = SquarifiedTreemapEngine.calculate_layout(items_copy, bounds)
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.fillRect(self.rect(), QColor("#0b1120"))

        if not self.tiles:
            painter.setPen(QColor("#64748b"))
            painter.setFont(QFont("Segoe UI", 12))
            painter.drawText(self.rect(), Qt.AlignCenter, "Keine Dateien oder Verzeichnisse vorhanden.")
            return

        font_name = QFont("Segoe UI", 9, QFont.Bold)
        font_size = QFont("Segoe UI", 8)

        for item in self.tiles:
            r: QRectF = item["rect"]
            if r.width() < 1 or r.height() < 1:
                continue

            cat = item.get("category", "other")
            base_color = self.CATEGORY_COLORS.get(cat, QColor("#64748b"))

            if r.width() < 4 or r.height() < 4:
                painter.fillRect(r, base_color)
                continue

            grad = QLinearGradient(r.topLeft(), r.bottomRight())

            if item == self.selected_tile:
                grad.setColorAt(0.0, base_color.lighter(150))
                grad.setColorAt(1.0, base_color.lighter(110))
            elif item == self.hovered_tile:
                grad.setColorAt(0.0, base_color.lighter(130))
                grad.setColorAt(1.0, base_color)
            else:
                grad.setColorAt(0.0, base_color)
                grad.setColorAt(1.0, base_color.darker(130))

            painter.setBrush(QBrush(grad))
            border_color = QColor("#ffffff") if item == self.selected_tile else (QColor("#38bdf8") if item == self.hovered_tile else QColor("#0f172a"))
            painter.setPen(QPen(border_color, 1.5 if item in (self.selected_tile, self.hovered_tile) else 1.0))
            painter.drawRoundedRect(r.adjusted(1, 1, -1, -1), 3.0, 3.0)

            if r.width() >= 45 and r.height() >= 26:
                painter.setClipRect(r.adjusted(3, 2, -3, -2))
                painter.setPen(QColor("#ffffff"))
                painter.setFont(font_name)
                name_str = ("📁 " if item.get("is_dir") else "") + item.get("name", "")
                painter.drawText(int(r.x() + 5), int(r.y() + 14), name_str)

                if r.height() >= 40:
                    painter.setFont(font_size)
                    painter.setPen(QColor("#cbd5e1"))
                    painter.drawText(int(r.x() + 5), int(r.y() + 29), format_bytes(item.get("size", 0)))
                painter.setClipping(False)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        found: Optional[Dict[str, Any]] = None
        for item in self.tiles:
            if item["rect"].contains(pos):
                found = item
                break

        if found != self.hovered_tile:
            self.hovered_tile = found
            self.update()
            if found:
                self.sig_tile_hovered.emit(found)
                tt = f"{found.get('name')}\nGröße: {format_bytes(found.get('size', 0))}\nKategorie: {found.get('category', 'Unbekannt')}"
                if found.get("is_dir"):
                    tt += f"\nDateien: {found.get('file_count', 0):,}"
                self.setToolTip(tt)
            else:
                self.setToolTip("")
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            pos = event.position()
            for item in self.tiles:
                if item["rect"].contains(pos):
                    self.selected_tile = item
                    self.update()
                    self.sig_tile_selected.emit(item)
                    break
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton and self.selected_tile:
            self.sig_tile_double_clicked.emit(self.selected_tile)
        super().mouseDoubleClickEvent(event)

