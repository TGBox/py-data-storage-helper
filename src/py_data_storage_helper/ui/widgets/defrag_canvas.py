from PySide6.QtCore import QRectF
from PySide6.QtCore import QTimer
import math
from typing import List, Dict, Any, Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPaintEvent


class DefragClusterMapWidget(QWidget):
    STATE_FREE = 0
    STATE_ALLOCATED = 1
    STATE_FRAGMENTED = 2
    STATE_SYSTEM_MFT = 3
    STATE_OPTIMIZING = 4
    STATE_OPTIMIZED = 5

    CLUSTER_COLORS = {
        STATE_FREE: QColor("#1e293b"),
        STATE_ALLOCATED: QColor("#2563eb"),
        STATE_FRAGMENTED: QColor("#ef4444"),
        STATE_SYSTEM_MFT: QColor("#f59e0b"),
        STATE_OPTIMIZING: QColor("#10b981"),
        STATE_OPTIMIZED: QColor("#06b6d4")
    }

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumHeight(190)
        self.cols = 50
        self.rows = 18
        self.total_blocks = self.cols * self.rows
        self.blocks: List[int] = [self.STATE_FREE] * self.total_blocks
        self.head_index = -1
        self.hovered_index = -1
        self.is_defragging = False

        self.pulse_timer = QTimer(self)
        self.pulse_timer.setInterval(120)
        self.pulse_state = 0
        self.pulse_timer.timeout.connect(self._on_pulse)

    def initialize_drive(self, total_bytes: int, free_bytes: int, is_ssd: bool) -> None:
        self.blocks = [self.STATE_FREE] * self.total_blocks
        self.head_index = -1
        self.is_defragging = False
        self.pulse_timer.stop()

        if total_bytes <= 0 or is_ssd:
            self.update()
            return

        used_bytes = max(0, total_bytes - free_bytes)
        used_ratio = min(0.98, max(0.05, used_bytes / total_bytes))
        used_blocks = int(self.total_blocks * used_ratio)

        mft_count = max(4, int(self.total_blocks * 0.035))
        for i in range(mft_count):
            self.blocks[i] = self.STATE_SYSTEM_MFT

        frag_count = max(10, int(used_blocks * 0.14))
        allocated_indices = list(range(mft_count, used_blocks))
        frag_step = max(2, len(allocated_indices) // frag_count) if frag_count > 0 else 5
        frag_indices = set(allocated_indices[::frag_step][:frag_count])

        for idx in range(mft_count, self.total_blocks):
            if idx < used_blocks:
                self.blocks[idx] = self.STATE_FRAGMENTED if idx in frag_indices else self.STATE_ALLOCATED
            else:
                self.blocks[idx] = self.STATE_FREE
        self.update()

    def start_animation(self) -> None:
        self.is_defragging = True
        self.head_index = 0
        self.pulse_timer.start()
        self.update()

    def update_progress(self, pct: int, msg: str = "") -> None:
        if not self.is_defragging:
            self.start_animation()
        pct = max(0, min(100, pct))
        target_index = int((pct / 100.0) * (self.total_blocks - 1))
        self.head_index = target_index

        for i in range(target_index):
            if self.blocks[i] == self.STATE_FRAGMENTED:
                self.blocks[i] = self.STATE_OPTIMIZED
            elif self.blocks[i] == self.STATE_FREE and i < int(self.total_blocks * 0.7):
                if i % 7 == 0:
                    self.blocks[i] = self.STATE_OPTIMIZED
        self.update()

    def complete_defrag(self) -> None:
        self.is_defragging = False
        self.head_index = -1
        self.pulse_timer.stop()
        for i in range(self.total_blocks):
            if self.blocks[i] in (self.STATE_FRAGMENTED, self.STATE_OPTIMIZED):
                self.blocks[i] = self.STATE_ALLOCATED
        self.update()

    def _on_pulse(self) -> None:
        self.pulse_state = (self.pulse_state + 1) % 4
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(0, 0, self.width(), self.height(), QColor("#0b1120"))

        margin_x, margin_y, spacing = 4, 4, 2
        avail_w = self.width() - (2 * margin_x)
        avail_h = self.height() - (2 * margin_y)
        cell_w = max(4.0, (avail_w - (self.cols - 1) * spacing) / float(self.cols))
        cell_h = max(4.0, (avail_h - (self.rows - 1) * spacing) / float(self.rows))
        pen_border = QPen(QColor("#0f172a"), 1)

        for r in range(self.rows):
            for c in range(self.cols):
                idx = r * self.cols + c
                if idx >= self.total_blocks:
                    break
                x = margin_x + c * (cell_w + spacing)
                y = margin_y + r * (cell_h + spacing)
                rect = QRectF(x, y, cell_w, cell_h)
                state = self.blocks[idx]
                is_head = (idx == self.head_index and self.is_defragging)

                if is_head:
                    glow = QColor("#22c55e") if self.pulse_state % 2 == 0 else QColor("#86efac")
                    painter.fillRect(rect, glow)
                    painter.setPen(QPen(QColor("#ffffff"), 1.5))
                    painter.drawRect(rect)
                else:
                    col = self.CLUSTER_COLORS.get(state, QColor("#1e293b"))
                    if idx == self.hovered_index:
                        col = col.lighter(140)
                    painter.fillRect(rect, col)
                    painter.setPen(pen_border)
                    painter.drawRect(rect)

