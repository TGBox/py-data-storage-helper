import platform
import os
import sys
import ctypes
import subprocess
from typing import Optional, Dict, Any
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QStackedWidget, QFrame,
    QStatusBar, QMessageBox, QApplication, QDialog
)

from ..constants import APP_NAME
from ..core.windows import is_running_as_admin
from ..core.database import DatabaseManager
from ..core.plan import StoragePlan
from ..workers.device_watcher import DeviceWatcher
from .widgets.admin_banner import AdminBanner
from .widgets.arrival_dialog import DriveArrivalDialog
from .views.overview_view import DriveOverviewView
from .views.catalog_view import CatalogExplorerView
from .views.treemap_view import StorageTreemapView
from .views.duplicate_view import DuplicateFinderView
from .views.transform_view import BatchTransformView
from .views.visual_view import VisualPlanningView
from .views.plan_view import PlanManagerView
from .views.queue_view import TransferQueueView
from .views.defrag_view import DefragView
from .views.journal_view import UndoJournalView
from .views.status_view import SystemStatusView


class MainWindow(QMainWindow):
    def __init__(self, initial_plan_path: Optional[str] = None):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} - Windows Edition")
        self.resize(1380, 880)
        self.setMinimumSize(1100, 720)

        self.db = DatabaseManager()
        self.is_admin = is_running_as_admin()
        self.shared_plan = StoragePlan("Festplatten-Konsolidierung")

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        self.admin_banner = AdminBanner(self.is_admin)
        self.admin_banner.sig_request_elevation.connect(self.handle_elevation_relaunch)
        main_layout.addWidget(self.admin_banner)

        body_widget = QWidget()
        body_layout = QHBoxLayout(body_widget)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        sidebar_frame = QFrame()
        sidebar_frame.setObjectName("SidebarFrame")
        sidebar_frame.setFixedWidth(250)
        sidebar_layout = QVBoxLayout(sidebar_frame)
        sidebar_layout.setContentsMargins(12, 20, 12, 20)
        sidebar_layout.setSpacing(4)

        logo_lbl = QLabel(f"💾 {APP_NAME}")
        logo_lbl.setStyleSheet("font-size: 15px; font-weight: 800; color: #f8fafc; padding: 0 0 16px 8px;")
        sidebar_layout.addWidget(logo_lbl)

        self.nav_buttons = []
        self.btn_nav_drives = self.create_nav_button("💽 Laufwerke & Indexer", 0)
        self.btn_nav_catalog = self.create_nav_button("🔍 Datei-Katalog", 1)
        self.btn_nav_treemap = self.create_nav_button("🗺️ Speicher-Treemap", 2)
        self.btn_nav_duplicates = self.create_nav_button("👥 Duplikate & Redundanzen", 3)
        self.btn_nav_batch = self.create_nav_button("🏷️ Batch-Transformation", 4)
        self.btn_nav_visual = self.create_nav_button("🎨 Visuelle Planung", 5)
        self.btn_nav_plan = self.create_nav_button("📋 Plan-Manager (.stplan)", 6)
        self.btn_nav_queue = self.create_nav_button("🚀 Transfer-Queue & Ausführung", 7)
        self.btn_nav_defrag = self.create_nav_button("🧹 Defragmentierung (HDD)", 8)
        self.btn_nav_journal = self.create_nav_button("🔄 Undo & Historie", 9)
        self.btn_nav_system = self.create_nav_button("⚙️ System-Status", 10)

        for btn in [self.btn_nav_drives, self.btn_nav_catalog, self.btn_nav_treemap,
                    self.btn_nav_duplicates, self.btn_nav_batch, self.btn_nav_visual,
                    self.btn_nav_plan, self.btn_nav_queue, self.btn_nav_defrag,
                    self.btn_nav_journal, self.btn_nav_system]:
            sidebar_layout.addWidget(btn)
            self.nav_buttons.append(btn)

        sidebar_layout.addStretch()
        body_layout.addWidget(sidebar_frame)

        self.stack = QStackedWidget()
        self.view_drives = DriveOverviewView(self.db)
        self.view_catalog = CatalogExplorerView(self.db)
        self.view_treemap = StorageTreemapView(self.db, self.shared_plan)
        self.view_duplicates = DuplicateFinderView(self.db)
        self.view_batch = BatchTransformView(self.db)
        self.view_visual = VisualPlanningView(self.db, self.shared_plan)
        self.view_plan = PlanManagerView(self.db, self.shared_plan)
        self.view_queue = TransferQueueView(self.db, self.shared_plan)
        self.view_defrag = DefragView(self.db)
        self.view_journal = UndoJournalView(self.db)
        self.view_system = SystemStatusView(self.db)

        self.view_visual.sig_plan_updated.connect(self.view_plan.refresh_table)
        self.view_plan.sig_request_execution.connect(lambda: self.switch_nav(7))

        self.stack.addWidget(self.view_drives)       # 0
        self.stack.addWidget(self.view_catalog)      # 1
        self.stack.addWidget(self.view_treemap)      # 2
        self.stack.addWidget(self.view_duplicates)   # 3
        self.stack.addWidget(self.view_batch)        # 4
        self.stack.addWidget(self.view_visual)       # 5
        self.stack.addWidget(self.view_plan)         # 6
        self.stack.addWidget(self.view_queue)        # 7
        self.stack.addWidget(self.view_defrag)       # 8
        self.stack.addWidget(self.view_journal)      # 9
        self.stack.addWidget(self.view_system)       # 10

        body_layout.addWidget(self.stack, 1)
        main_layout.addWidget(body_widget, 1)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("System initialisiert. Bereit.")

        if initial_plan_path:
            self.load_resume_plan(initial_plan_path)

        self.device_watcher = DeviceWatcher()
        self.device_watcher.sig_drive_arrived.connect(self.on_device_arrived)
        self.device_watcher.sig_drive_removed.connect(self.on_device_removed)
        self.device_watcher.start()

        self.switch_nav(0)

    @Slot(dict)
    def on_device_arrived(self, vol_info: Dict[str, Any]) -> None:
        with self.db.get_connection() as conn:
            row = conn.execute("SELECT id FROM volumes WHERE id = ?", (vol_info["id"],)).fetchone()
            is_known = row is not None

        self.db.upsert_volume(vol_info)
        self.status_bar.showMessage(f"🔌 Neues Laufwerk erkannt: {vol_info['letter']} [{vol_info['label']}]", 8000)
        self.view_drives.refresh_drives()

        dialog = DriveArrivalDialog(self, vol_info, is_known=is_known)
        if dialog.exec() == QDialog.Accepted:
            act = dialog.selected_action
            if act == DriveArrivalDialog.ACTION_INDEX_FULL:
                self.switch_nav(0)
                self.view_drives.start_indexing(vol_info)
            elif act == DriveArrivalDialog.ACTION_ADD_TO_PLAN:
                self.switch_nav(5)
                self.view_visual.refresh_visuals()

    @Slot(str)
    def on_device_removed(self, letter: str) -> None:
        self.status_bar.showMessage(f"⏏️ Laufwerk {letter}\\ getrennt.", 8000)
        self.view_drives.refresh_drives()
        self.view_visual.refresh_visuals()

    def closeEvent(self, event) -> None:
        transfer = self.view_queue.worker
        defrag = self.view_defrag.worker
        busy = []
        if transfer and transfer.isRunning():
            busy.append("ein Transfer")
        if defrag and defrag.isRunning():
            busy.append("eine Defragmentierung")
        if busy:
            answer = QMessageBox.question(
                self, "Vorgang läuft",
                f"Es läuft noch {' und '.join(busy)}. Abbrechen und beenden?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return

        workers = [w for w in (self.view_drives.active_worker, self.view_duplicates.worker, transfer, defrag)
                   if w and w.isRunning()]
        for w in workers:
            w.blockSignals(True)  # keine Abschluss-Dialoge mehr nach dem Schließen
            w.cancel()
        watcher = getattr(self, "device_watcher", None)
        if watcher and watcher.isRunning():
            watcher.stop()
            workers.append(watcher)

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for w in workers:
                w.wait(15000)
        finally:
            QApplication.restoreOverrideCursor()
        super().closeEvent(event)

    def create_nav_button(self, text: str, index: int) -> QPushButton:
        btn = QPushButton(text)
        btn.setProperty("class", "nav-btn")
        btn.setCheckable(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self.switch_nav(index))
        return btn

    def switch_nav(self, index: int) -> None:
        for idx, btn in enumerate(self.nav_buttons):
            btn.setChecked(idx == index)
        self.stack.setCurrentIndex(index)

        if index == 1:
            self.view_catalog.refresh_volume_list()
            self.view_catalog.apply_search()
        elif index == 2:
            self.view_treemap.refresh_volume_list()
        elif index == 3:
            self.view_duplicates.refresh_volume_list()
        elif index == 4:
            self.view_batch.refresh_volume_list()
        elif index == 5:
            self.view_visual.refresh_visuals()
        elif index == 6:
            self.view_plan.refresh_table()
        elif index == 7:
            self.view_queue.refresh_table()
        elif index == 8:
            self.view_defrag.refresh_drives()
        elif index == 9:
            self.view_journal.refresh_logs()

    def handle_elevation_relaunch(self) -> None:
        temp_dir = os.path.join(os.path.expanduser("~"), ".storage_manager")
        os.makedirs(temp_dir, exist_ok=True)
        temp_plan_file = os.path.join(temp_dir, "resume_plan.stplan")

        saved = self.shared_plan.save_to_file(temp_plan_file)
        if not saved:
            QMessageBox.critical(self, "Fehler", "Plan konnte nicht gesichert werden.")
            return

        if platform.system() != "Windows":
            return

        try:
            params = f'"{sys.argv[0]}" --load-plan "{temp_plan_file}"'
            result = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
            if int(result) > 32:
                QApplication.quit()
        except Exception as ex:
            QMessageBox.critical(self, "Fehler", str(ex))

    def load_resume_plan(self, path: str) -> None:
        plan = StoragePlan.load_from_file(path)
        if plan:
            self.shared_plan.replace_with(plan)
            self.view_plan.refresh_table()
            self.view_queue.refresh_table()
            self.switch_nav(7)

