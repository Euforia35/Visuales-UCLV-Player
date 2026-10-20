"""
cards.py
--------
Componentes visuales tipo "plataforma de streaming":

- MediaCard: tarjeta vertical (póster 2:3 + título + meta + barra de
  progreso) con hover animado (zoom sutil del póster + borde de acento).
- CardRow: fila horizontal con título y scroll (flechas ‹ ›), como las
  filas del home de Netflix.

Los pósters llegan como QPixmap ya escalado (se redondean con máscara
acá en el hilo principal; al ser tamaños chicos el costo es mínimo).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import Qt, QSize, QVariantAnimation, QEasingCurve, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor, QPainterPath
from PySide6.QtWidgets import (
    QWidget, QFrame, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QToolButton, QSizePolicy,
)

import theme

CARD_WIDTH = 152
CARD_HEIGHT = CARD_WIDTH * 3 // 2 + 66   # póster + título/meta/progreso
CARD_PAD_X = 6                           # margen interno para el borde de hover
CARD_PAD_Y = 4
POSTER_SIZE = (CARD_WIDTH, CARD_WIDTH * 3 // 2)  # 152x228, ratio 2:3
HOVER_SCALE = 1.07


@dataclass
class CardData:
    """Datos de un ítem mostrado como tarjeta."""
    key: str                      # identificador único (normalmente la url)
    title: str
    url: str = ""                 # carpeta o video a abrir
    meta: str = ""                # línea chica: "2014 · ★ 8.4"
    is_video: bool = False
    progress: float | None = None  # 0..1, para la barra de progreso
    payload: object = field(default=None, repr=False)  # datos extra (posición, etc.)


def rounded_pixmap(pix: QPixmap, radius: int = theme.POSTER_RADIUS) -> QPixmap:
    """Póster con esquinas redondeadas (máscara recortada con alpha)."""
    if pix.isNull():
        return pix
    out = QPixmap(pix.size())
    out.fill(Qt.transparent)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0.0, 0.0, float(pix.width()), float(pix.height()),
                        float(radius), float(radius))
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pix)
    painter.end()
    return out


def cover_pixmap(pix: QPixmap, size) -> QPixmap:
    """Escala KeepAspectRatioByExpanding (llena el área, recorta el exceso).
    Acepta QSize o (ancho, alto)."""
    if not isinstance(size, QSize):
        size = QSize(int(size[0]), int(size[1]))
    return pix.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)


class ProgressLine(QWidget):
    """Barra de progreso delgada (estilo Netflix) para ver % visto."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._value: float | None = None
        self.setFixedHeight(3)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def set_value(self, value: float | None):
        self._value = value
        self.setVisible(value is not None)
        self.update()

    def paintEvent(self, event):
        if self._value is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255, 40))
        painter.drawRoundedRect(0, 0, w, h, h / 2, h / 2)
        painter.setBrush(QColor(theme.ACCENT))
        painter.drawRoundedRect(0, 0, max(h, int(w * min(self._value, 1.0))), h, h / 2, h / 2)


class MediaCard(QFrame):
    """Tarjeta de póster con hover animado. Emite activated(key)."""

    activated = Signal(str)
    show_menu = Signal(object)  # CardData, clic derecho

    def __init__(self, data: CardData, parent=None):
        super().__init__(parent)
        self.data = data
        self.setObjectName("mediaCard")
        # El borde de hover (2px) se pinta sobre el borde del widget: le
        # damos margen extra para que no lo recorte el QScrollArea ni el
        # layout de la fila (antes el borde derecho quedaba trunco).
        self.setFixedSize(CARD_WIDTH + CARD_PAD_X * 2, CARD_HEIGHT + CARD_PAD_Y * 2)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._source_pix: QPixmap | None = None
        self._scale = 1.0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(CARD_PAD_X, CARD_PAD_Y, CARD_PAD_X, CARD_PAD_Y)
        layout.setSpacing(0)

        poster_wrap = QWidget()
        poster_wrap.setFixedSize(CARD_WIDTH, CARD_WIDTH * 3 // 2)
        poster_wrap.setAttribute(Qt.WA_TranslucentBackground, True)
        self.poster_label = QLabel(poster_wrap)
        self.poster_label.setGeometry(0, 0, CARD_WIDTH, CARD_WIDTH * 3 // 2)
        self.poster_label.setAttribute(Qt.WA_TranslucentBackground, True)
        self._set_placeholder()
        layout.addWidget(poster_wrap)
        self._poster_wrap = poster_wrap

        layout.addSpacing(6)

        self.title_label = QLabel(self.data.title)
        self.title_label.setObjectName("cardTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setFixedHeight(32)
        layout.addWidget(self.title_label)

        self.meta_label = QLabel(self.data.meta)
        self.meta_label.setObjectName("cardMeta")
        layout.addWidget(self.meta_label)

        self.progress_line = ProgressLine()
        self.progress_line.set_value(self.data.progress)
        layout.addWidget(self.progress_line)
        layout.addStretch(1)

        # Animación de zoom del póster al hacer hover
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_scale_changed)

    # ------------------------------------------------------------------
    def _placeholder_pixmap(self) -> QPixmap:
        pix = QPixmap(CARD_WIDTH, CARD_WIDTH * 3 // 2)
        pix.fill(QColor(theme.SURFACE))
        painter = QPainter(pix)
        painter.setPen(QColor(theme.GLYPH_DIM))
        painter.setFont(self.font())
        glyph = "🎬" if self.data.is_video else "📁"
        painter.drawText(pix.rect(), Qt.AlignCenter, glyph)
        painter.end()
        return rounded_pixmap(pix)

    def _set_placeholder(self):
        self._source_pix = self._placeholder_pixmap()
        self.poster_label.setPixmap(self._source_pix)

    def set_poster(self, pix: QPixmap):
        """pix ya escalado a POSTER_SIZE (se recorta/redonda acá)."""
        if pix.isNull():
            return
        self._source_pix = rounded_pixmap(cover_pixmap(pix, QSize(*POSTER_SIZE)))
        self._apply_scale()

    def set_meta_text(self, text: str):
        self.data.meta = text
        try:
            self.meta_label.setText(text)
        except RuntimeError:
            pass  # el widget ya fue destruido (la fila se reconstruyó)

    def set_title(self, text: str):
        self.data.title = text
        try:
            self.title_label.setText(text)
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    def _apply_scale(self):
        if self._source_pix is None:
            return
        if abs(self._scale - 1.0) < 0.005:
            self.poster_label.setPixmap(self._source_pix)
            return
        size = self._source_pix.size() * self._scale
        size = QSize(max(1, round(size.width())), max(1, round(size.height())))
        scaled = self._source_pix.scaled(
            size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
        )
        # centrado dentro del área del póster
        x = (POSTER_SIZE[0] - scaled.width()) // 2
        y = (POSTER_SIZE[1] - scaled.height()) // 2
        holder = QPixmap(*POSTER_SIZE)
        holder.fill(Qt.transparent)
        painter = QPainter(holder)
        painter.drawPixmap(x, y, scaled)
        painter.end()
        self.poster_label.setPixmap(holder)

    def _on_scale_changed(self, value):
        self._scale = float(value)
        self._apply_scale()

    def _animate_to(self, end: float):
        self._anim.stop()
        self._anim.setStartValue(self._scale)
        self._anim.setEndValue(end)
        self._anim.start()

    def enterEvent(self, event):
        self.setProperty("hover", True)
        self._repolish()
        self._animate_to(HOVER_SCALE)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setProperty("hover", False)
        self._repolish()
        self._animate_to(1.0)
        super().leaveEvent(event)

    def _repolish(self):
        style = self.style()
        style.unpolish(self)
        style.polish(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.activated.emit(self.data.key)
        elif event.button() == Qt.RightButton:
            self.show_menu.emit(self.data)
        super().mousePressEvent(event)


class CardRow(QWidget):
    """Fila horizontal: título + scroll de MediaCards + flechas ‹ ›."""

    activated = Signal(object)   # CardData
    show_menu = Signal(object)   # CardData

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self._cards: dict[str, MediaCard] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 8)
        outer.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(6)
        title_label = QLabel(title)
        title_label.setObjectName("rowTitle")
        header.addWidget(title_label)
        header.addStretch(1)

        self.prev_btn = QToolButton()
        self.prev_btn.setObjectName("rowArrow")
        self.prev_btn.setText("‹")
        self.prev_btn.setFixedSize(28, 28)
        self.next_btn = QToolButton()
        self.next_btn.setObjectName("rowArrow")
        self.next_btn.setText("›")
        self.next_btn.setFixedSize(28, 28)
        self.prev_btn.clicked.connect(lambda: self._scroll_page(-1))
        self.next_btn.clicked.connect(lambda: self._scroll_page(1))
        header.addWidget(self.prev_btn)
        header.addWidget(self.next_btn)
        outer.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.scroll.setFixedHeight(CARD_HEIGHT + CARD_PAD_Y * 2 + 16)

        self._strip = QWidget()
        self._strip_layout = QHBoxLayout(self._strip)
        self._strip_layout.setContentsMargins(0, 2, 20, 2)
        self._strip_layout.setSpacing(2)
        self._strip_layout.addStretch(1)
        self.scroll.setWidget(self._strip)
        outer.addWidget(self.scroll)

    # ------------------------------------------------------------------
    def _scroll_page(self, direction: int):
        try:
            bar = self.scroll.horizontalScrollBar()
        except RuntimeError:
            return  # fila ya destruida
        bar.setValue(bar.value() + direction * max(200, int(self.scroll.width() * 0.8)))

    def set_cards(self, cards: list[CardData]):
        while self._strip_layout.count() > 1:  # deja el stretch final
            item = self._strip_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)   # lo desparenta YA (no queda accesible)
                w.deleteLater()
        self._cards.clear()
        for data in cards:
            card = MediaCard(data)
            card.activated.connect(self.activated.emit)
            card.show_menu.connect(self.show_menu.emit)
            self._strip_layout.insertWidget(self._strip_layout.count() - 1, card)
            self._cards[data.key] = card

    def card(self, key: str) -> MediaCard | None:
        card = self._cards.get(key)
        if card is None:
            return None
        # el widget pudo haber sido destruido por una reconstrucción de la fila
        try:
            card.objectName()
        except RuntimeError:
            return None
        return card

    def update_data(self, key: str, title: str | None = None, meta: str | None = None):
        card = self.card(key)
        if not card:
            return
        if title is not None:
            card.set_title(title)
        if meta is not None:
            card.set_meta_text(meta)
