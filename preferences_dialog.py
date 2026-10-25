"""
preferences_dialog.py
---------------------
Diálogo de preferencias de reproducción: búfer/caché de video y estilo
de los subtítulos. Los valores se guardan en ``config.json`` y
``PlayerWidget`` los aplica sin reiniciar la app.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QLabel, QSpinBox, QVBoxLayout,
)

from config_store import ConfigStore
from player_prefs import (
    DEFAULT_CACHE_MAX_MB, DEFAULT_CACHE_SECS, DEFAULT_SUB_COLOR,
    DEFAULT_SUB_FONT_SIZE, MAX_CACHE_MB, MAX_CACHE_SECS,
    MAX_SUB_FONT_SIZE, MIN_CACHE_MB, MIN_CACHE_SECS, MIN_SUB_FONT_SIZE,
    SUB_COLORS, SUB_FONT_STEP, cache_max_mb, cache_secs, sub_color,
    sub_font_size,
)


def _color_icon(hex_value: str, size: int = 14) -> QIcon:
    """Cuadradito del color para el combo (mpv usa #AARRGGBB)."""
    text = hex_value.lstrip("#")
    if len(text) == 8:          # AARRGGBB
        r, g, b = text[2:4], text[4:6], text[6:8]
    else:                        # RRGGBB
        r, g, b = text[0:2], text[2:4], text[4:6]
    pix = QPixmap(size, size)
    pix.fill(QColor(int(r, 16), int(g, 16), int(b, 16)))
    return QIcon(pix)


class PreferencesDialog(QDialog):
    def __init__(self, config: ConfigStore, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Preferencias")
        self.setModal(True)
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        # --- Video / caché ------------------------------------------------
        cache_box = QGroupBox("Video y caché")
        cache_form = QFormLayout(cache_box)
        self.cache_minutes = QSpinBox()
        self.cache_minutes.setRange(MIN_CACHE_SECS // 60 or 1, MAX_CACHE_SECS // 60)
        self.cache_minutes.setSuffix(" min")
        self.cache_minutes.setToolTip(
            "Cuántos segundos de video se descargan por adelantado.\n"
            "Un colchón grande evita que el video se trabe cuando la\n"
            "conexión al servidor tiene baches."
        )
        self.cache_mb = QSpinBox()
        self.cache_mb.setRange(MIN_CACHE_MB, MAX_CACHE_MB)
        self.cache_mb.setSingleStep(32)
        self.cache_mb.setSuffix(" MB")
        self.cache_mb.setToolTip(
            "Tope de memoria que puede usar el búfer del reproductor."
        )
        cache_form.addRow("Colchón de video:", self.cache_minutes)
        cache_form.addRow("Memoria máxima:", self.cache_mb)
        hint = QLabel(
            "Más colchón tolera mejor un servidor lento, pero usa más "
            "memoria y tarda un poco más en empezar. El cambio se aplica "
            "enseguida, también al video que estés viendo."
        )
        hint.setWordWrap(True)
        hint.setObjectName("statusLabel")
        cache_form.addRow(hint)
        layout.addWidget(cache_box)

        # --- Subtítulos ---------------------------------------------------
        sub_box = QGroupBox("Subtítulos")
        sub_form = QFormLayout(sub_box)
        self.sub_size = QSpinBox()
        self.sub_size.setRange(MIN_SUB_FONT_SIZE, MAX_SUB_FONT_SIZE)
        self.sub_size.setSingleStep(SUB_FONT_STEP)
        self.sub_size.setSuffix(" px")
        self.sub_size.setToolTip("También podés cambiarlo con Shift+↑ / Shift+↓.")
        self.sub_color = QComboBox()
        for name, hex_value in SUB_COLORS:
            self.sub_color.addItem(_color_icon(hex_value), name, hex_value)
        self.sub_color.setToolTip("También podés cambiarlo con la tecla C.")
        sub_form.addRow("Tamaño:", self.sub_size)
        sub_form.addRow("Color:", self.sub_color)
        sub_hint = QLabel(
            "Atajos durante la reproducción: Shift+↑ / Shift+↓ (o + / −) "
            "cambian el tamaño y C cambia el color."
        )
        sub_hint.setWordWrap(True)
        sub_hint.setObjectName("statusLabel")
        sub_form.addRow(sub_hint)
        layout.addWidget(sub_box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.button(QDialogButtonBox.Save).setText("Guardar")
        buttons.button(QDialogButtonBox.Cancel).setText("Cancelar")
        restore = buttons.addButton("Restaurar", QDialogButtonBox.ResetRole)
        restore.clicked.connect(self._restore_defaults)
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._load_values()

    # ------------------------------------------------------------------
    def _load_values(self):
        secs = cache_secs(self.config)
        minutes = max(self.cache_minutes.minimum(), round(secs / 60))
        self.cache_minutes.setValue(minutes)
        self.cache_mb.setValue(cache_max_mb(self.config))
        self.sub_size.setValue(sub_font_size(self.config))

        current = sub_color(self.config)
        for i in range(self.sub_color.count()):
            if self.sub_color.itemData(i) == current:
                self.sub_color.setCurrentIndex(i)
                break

    def _restore_defaults(self):
        self.cache_minutes.setValue(round(DEFAULT_CACHE_SECS / 60))
        self.cache_mb.setValue(DEFAULT_CACHE_MAX_MB)
        self.sub_size.setValue(DEFAULT_SUB_FONT_SIZE)
        index = self.sub_color.findData(DEFAULT_SUB_COLOR)
        if index >= 0:
            self.sub_color.setCurrentIndex(index)
        else:
            self.sub_color.setCurrentIndex(0)

    def _save_and_accept(self):
        self.config.set("video_cache_secs", self.cache_minutes.value() * 60)
        self.config.set("video_cache_max_mb", self.cache_mb.value())
        self.config.set("sub_font_size", self.sub_size.value())
        self.config.set("sub_color", self.sub_color.currentData())
        self.accept()
