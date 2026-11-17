from typing import Dict, Any
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFrame, QGroupBox, QButtonGroup, QRadioButton
)
from ...core.utils import format_bytes


class DriveArrivalDialog(QDialog):
    ACTION_INDEX_FULL = 1
    ACTION_ADD_TO_PLAN = 2
    ACTION_IGNORE = 0

    def __init__(self, parent: QWidget, drive_data: Dict[str, Any], is_known: bool):
        super().__init__(parent)
        self.drive_data = drive_data
        self.selected_action = self.ACTION_INDEX_FULL
        self.setWindowTitle("🔌 Neues Speicherlaufwerk erkannt!")
        self.resize(540, 340)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        header_card = QFrame()
        header_card.setObjectName("HeaderCard")
        header_card.setStyleSheet("QFrame#HeaderCard { background-color: #1e293b; border-radius: 8px; padding: 14px; }")
        h_layout = QVBoxLayout(header_card)

        lbl_title = QLabel(f"💽 Neues Laufwerk gefunden: <b>{drive_data['letter']} [{drive_data['label']}]</b>")
        lbl_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #38bdf8;")
        h_layout.addWidget(lbl_title)

        info_str = (
            f"Typ: {drive_data.get('drive_type', 'Unbekannt')} ({'SSD' if drive_data.get('is_ssd') else 'HDD'}) | "
            f"Dateisystem: {drive_data.get('file_system', 'NTFS')}<br>"
            f"Gesamtkapazität: <b>{format_bytes(drive_data['total_space'])}</b> | "
            f"Freier Speicher: <b style='color:#10b981;'>{format_bytes(drive_data['free_space'])}</b>"
        )
        lbl_info = QLabel(info_str)
        lbl_info.setStyleSheet("color: #cbd5e1; font-size: 12px; margin-top: 4px;")
        h_layout.addWidget(lbl_info)

        status_note = "Dieses Laufwerk ist bereits in der lokalen Datenbank erfasst." if is_known else "Dieses Laufwerk wurde noch nicht indiziert."
        lbl_status = QLabel(f"ℹ️ {status_note}")
        lbl_status.setStyleSheet("color: #94a3b8; font-size: 11px; margin-top: 4px;")
        h_layout.addWidget(lbl_status)
        layout.addWidget(header_card)

        group_actions = QGroupBox("Auswahl der Folgeaktion:")
        a_layout = QVBoxLayout(group_actions)
        a_layout.setSpacing(8)

        self.btn_grp = QButtonGroup(self)
        self.rb_full = QRadioButton("Vollständig indizieren (Dateien && Ordnerhierarchie katalogisieren)")
        self.rb_full.setChecked(True)
        self.rb_plan = QRadioButton("Direkt in die visuelle Speicherplanung einbinden")
        self.rb_ignore = QRadioButton("Vorläufig ignorieren (keine automatische Aktion)")

        self.btn_grp.addButton(self.rb_full, self.ACTION_INDEX_FULL)
        self.btn_grp.addButton(self.rb_plan, self.ACTION_ADD_TO_PLAN)
        self.btn_grp.addButton(self.rb_ignore, self.ACTION_IGNORE)

        a_layout.addWidget(self.rb_full)
        a_layout.addWidget(self.rb_plan)
        a_layout.addWidget(self.rb_ignore)
        layout.addWidget(group_actions)

        btn_box = QHBoxLayout()
        btn_box.addStretch()

        btn_cancel = QPushButton("Schließen")
        btn_cancel.setProperty("class", "action-secondary")
        btn_cancel.clicked.connect(self.reject)
        btn_box.addWidget(btn_cancel)

        btn_ok = QPushButton("Aktion jetzt starten")
        btn_ok.setProperty("class", "action-primary")
        btn_ok.clicked.connect(self.on_confirm)
        btn_box.addWidget(btn_ok)
        layout.addLayout(btn_box)

    def on_confirm(self) -> None:
        self.selected_action = self.btn_grp.checkedId()
        self.accept()

