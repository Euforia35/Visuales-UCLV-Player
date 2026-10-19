"""
local_subs_dialog.py
--------------------
Pop-up para escoger subtítulos locales que están en la misma carpeta que
el video que se va a reproducir.

Útil cuando los nombres no coinciden y la carga automática no los empareja:
el diálogo lista TODOS los archivos de subtítulo de la carpeta y deja al
usuario marcar cuáles cargar.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton,
)


class LocalSubsDialog(QDialog):
    """Lista los subtítulos de la carpeta y deja elegir cuáles cargar.

    Cierre:
      - "Cargar seleccionados" -> chosen = URLs marcadas.
      - "Reproducir sin subtítulos" -> chosen = [].
      - "Cancelar"/cerrar -> chosen = None (el llamador aplica su
        comportamiento por defecto, ej. los subtítulos automáticos).
    """

    def __init__(
        self,
        video_name: str,
        subs: list[dict],          # [{"url": str, "name": str}, ...]
        preselect: list[str] | None = None,  # URLs a marcar por defecto
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Elegir subtítulos de la carpeta")
        self.resize(520, 400)
        self._chosen: list[str] | None = None

        preselect_set = set(preselect or [])

        layout = QVBoxLayout(self)

        header = QLabel(
            f"Video: <b>{video_name}</b><br>"
            f"Se encontraron {len(subs)} archivo(s) de subtítulo en la misma carpeta. "
            "Marcá el o los que quieras usar (el primero marcado será el que se muestre)."
        )
        header.setWordWrap(True)
        layout.addWidget(header)

        self.list_widget = QListWidget()
        for s in subs:
            item = QListWidgetItem(s["name"])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(
                Qt.Checked if s["url"] in preselect_set else Qt.Unchecked
            )
            item.setData(Qt.UserRole, s["url"])
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget, stretch=1)

        if not subs:
            self.list_widget.addItem(QListWidgetItem("(sin archivos de subtítulo)"))

        hint = QLabel(
            "Tip: si el subtítulo elegido no sincroniza, probá con otro de la lista "
            "o buscá uno online con el botón 🌐 del reproductor."
        )
        hint.setWordWrap(True)
        hint.setObjectName("statusLabel")
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancelar")
        cancel_btn.clicked.connect(self.reject)
        none_btn = QPushButton("Reproducir sin subtítulos")
        none_btn.clicked.connect(self._on_none)
        load_btn = QPushButton("✓ Cargar seleccionados")
        load_btn.setObjectName("playHeroBtn")
        load_btn.clicked.connect(self._on_load)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(none_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(load_btn)
        layout.addLayout(btn_row)

    # ------------------------------------------------------------------
    @property
    def chosen(self) -> list[str] | None:
        """URLs elegidas, o None si el usuario canceló/cerró."""
        return self._chosen

    def _on_none(self):
        self._chosen = []
        self.accept()

    def _on_load(self):
        urls = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.Checked:
                urls.append(item.data(Qt.UserRole))
        self._chosen = urls
        self.accept()
