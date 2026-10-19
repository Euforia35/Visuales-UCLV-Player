"""
local_subs_dialog.py
--------------------
Diálogo para elegir uno o más subtítulos locales presentes en la misma
carpeta que el video que se va a reproducir.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QCheckBox,
)


class LocalSubsDialog(QDialog):
    """Permite al usuario elegir qué subtítulos locales cargar."""

    subs_selected = Signal(list)  # lista de URLs seleccionadas

    def __init__(self, video_name: str, subs: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Seleccionar subtítulos locales")
        self.resize(480, 360)
        self._subs = subs

        layout = QVBoxLayout(self)

        label = QLabel(
            f"Hay {len(subs)} archivo(s) de subtítulo en la misma carpeta de:\n"
            f"“{video_name}”\n\n"
            "Marcá los que querés cargar (se activará el primero marcado)."
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        self.list_widget = QListWidget()
        for s in subs:
            item = QListWidgetItem(s["name"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            item.setData(Qt.UserRole, s["url"])
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget, stretch=1)

        # Pre-seleccionar los que probablemente coincidan con el video
        # (heurística simple: nombre base contiene parte del video base)
        try:
            video_base = video_name.rsplit(".", 1)[0].lower()
            for i in range(self.list_widget.count()):
                item = self.list_widget.item(i)
                sub_name = item.text().lower()
                sub_base = sub_name.rsplit(".", 1)[0]
                if video_base in sub_base or sub_base in video_base:
                    item.setCheckState(Qt.Checked)
        except Exception:
            pass

        if self.list_widget.count() > 0:
            first = self.list_widget.item(0)
            if first.checkState() == Qt.Unchecked:
                # si nada coincidió, marcamos el primero por comodidad?
                # pero mejor no imponer; dejamos todo sin marcar y que elija
                pass

        btn_row = QHBoxLayout()
        self.none_btn = QPushButton("No cargar ninguno")
        self.none_btn.clicked.connect(self._on_none)
        self.load_btn = QPushButton("Cargar seleccionados")
        self.load_btn.setObjectName("playHeroBtn")
        self.load_btn.clicked.connect(self._on_load)
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.none_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(self.load_btn)
        layout.addLayout(btn_row)

    def _on_none(self):
        self.subs_selected.emit([])
        self.accept()

    def _on_load(self):
        selected = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.data(Qt.UserRole))
        # Si marcó varios, el primero marcado será el activo en mpv
        self.subs_selected.emit(selected)
        self.accept()
