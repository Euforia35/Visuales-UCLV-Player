"""
home_view.py
------------
Pantalla de inicio estilo plataforma de streaming: banner principal
("hero") con backdrop panorámico, degradado, título, chips de metadatos
y botón de reproducción, más filas horizontales de contenido
(Continuar viendo, Películas, Series, Infantiles, Favoritos…).

Los datos (CardData) los arma MainWindow en background; acá solo se
renderiza. Las imágenes llegan después vía set_poster/set_backdrop.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QVariantAnimation, QTimer, QEasingCurve, Signal
from PySide6.QtGui import QPixmap, QPainter, QColor, QLinearGradient
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QStackedLayout,
    QScrollArea, QPushButton, QSizePolicy,
)

import theme
from cards import CardData, CardRow

HERO_HEIGHT = 360
HERO_ROTATE_MS = 12000


class BackdropLabel(QWidget):
    """Imagen panorámica con scrim de degradado (hacia abajo y a la
    izquierda) para que el texto encima siempre sea legible — el mismo
    truco visual que usa Netflix en sus banners."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pix: QPixmap | None = None
        self._prev_pix: QPixmap | None = None
        self._t = 1.0
        self._fade = QVariantAnimation(self)
        self._fade.setDuration(450)
        self._fade.setEasingCurve(QEasingCurve.InOutCubic)
        self._fade.valueChanged.connect(self._on_fade)

    def set_pixmap(self, pix: QPixmap | None):
        if pix is None or pix.isNull():
            self._pix = None
            self._prev_pix = None
            self.update()
            return
        self._prev_pix = self._pix if self._pix is not None else None
        self._pix = pix
        if self._prev_pix is not None:
            self._t = 0.0
            self._fade.stop()
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
        else:
            self._t = 1.0
            self.update()

    def _on_fade(self, value):
        self._t = float(value)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = self.rect()
        painter.fillRect(rect, QColor(theme.SIDEBAR_BG))

        def draw_full(pix: QPixmap | None, opacity: float):
            if pix is None or pix.isNull() or opacity <= 0.01:
                return
            scaled = pix.scaled(
                rect.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            x = (rect.width() - scaled.width()) // 2
            y = (rect.height() - scaled.height()) // 2
            painter.setOpacity(opacity)
            painter.drawPixmap(x, y, scaled)
            painter.setOpacity(1.0)

        draw_full(self._prev_pix, 1.0 - self._t)
        draw_full(self._pix, self._t)

        # Scrim inferior (fundido hacia el fondo de la app)
        grad = QLinearGradient(0, rect.height() * 0.25, 0, float(rect.height()))
        grad.setColorAt(0.0, QColor(20, 22, 26, 0))
        grad.setColorAt(0.75, QColor(20, 22, 26, 210))
        grad.setColorAt(1.0, QColor(20, 22, 26, 255))
        painter.fillRect(rect, grad)

        # Scrim lateral izquierdo (legibilidad del texto)
        grad2 = QLinearGradient(0, 0, max(1.0, rect.width() * 0.7), 0)
        grad2.setColorAt(0.0, QColor(13, 15, 18, 210))
        grad2.setColorAt(1.0, QColor(13, 15, 18, 0))
        painter.fillRect(rect, grad2)
        painter.end()


class HeroBanner(QFrame):
    """Banner principal rotatorio. Emite play_requested(CardData) e
    info_requested(CardData)."""

    play_requested = Signal(object)
    info_requested = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(HERO_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._items: list[CardData] = []
        self._backdrops: dict[str, QPixmap] = {}
        self._index = 0

        # Backdrop y contenido superpuestos (StackAll), como el banner
        # de Netflix: imagen a pantalla completa + texto encima.
        stack = QStackedLayout()
        stack.setStackingMode(QStackedLayout.StackAll)

        self.backdrop = BackdropLabel()
        stack.addWidget(self.backdrop)

        content = QWidget()
        content.setAttribute(Qt.WA_TranslucentBackground, True)
        content.setAutoFillBackground(False)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(32, 36, 32, 26)
        content_layout.setSpacing(8)

        def _no_bg(label):
            """QSS global le da fondo a QWidget: los textos sobre el
            backdrop tienen que ser transparentes para no tapar la imagen."""
            label.setAttribute(Qt.WA_TranslucentBackground, True)
            label.setAutoFillBackground(False)
            label.setStyleSheet("background: transparent;")
            return label

        self.hero_meta = _no_bg(QLabel(""))
        self.hero_meta.setObjectName("heroMeta")
        content_layout.addWidget(self.hero_meta)

        self.hero_title = _no_bg(QLabel(""))
        self.hero_title.setObjectName("heroTitle")
        self.hero_title.setWordWrap(True)
        content_layout.addWidget(self.hero_title)

        self.hero_synopsis = _no_bg(QLabel(""))
        self.hero_synopsis.setObjectName("heroSynopsis")
        self.hero_synopsis.setWordWrap(True)
        self.hero_synopsis.setMaximumHeight(54)  # ~3 líneas
        content_layout.addWidget(self.hero_synopsis)

        content_layout.addSpacing(6)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.play_btn = QPushButton("▶  Reproducir")
        self.play_btn.setObjectName("playHeroBtn")
        self.play_btn.setCursor(Qt.PointingHandCursor)
        self.info_btn = QPushButton("ℹ  Más información")
        self.info_btn.setObjectName("ghostBtn")
        self.info_btn.setCursor(Qt.PointingHandCursor)
        buttons.addWidget(self.play_btn)
        buttons.addWidget(self.info_btn)
        buttons.addStretch(1)
        content_layout.addLayout(buttons)
        content_layout.addStretch(1)
        stack.addWidget(content)

        self.setLayout(stack)

        self.play_btn.clicked.connect(self._emit_play)
        self.info_btn.clicked.connect(self._emit_info)

        self._timer = QTimer(self)
        self._timer.setInterval(HERO_ROTATE_MS)
        self._timer.timeout.connect(self._rotate)

    # ------------------------------------------------------------------
    def _emit_play(self):
        if self._items:
            self.play_requested.emit(self._items[self._index])

    def _emit_info(self):
        if self._items:
            self.info_requested.emit(self._items[self._index])

    def set_items(self, items: list[CardData]):
        self._items = items
        self._index = 0
        self.setVisible(bool(items))
        if items:
            self._apply_item(animate=False)
            self._timer.start()
        else:
            self._timer.stop()
            self.backdrop.set_pixmap(None)

    def set_backdrop(self, key: str, pix: QPixmap):
        """Backdrop panorámico para el ítem con esa key (si es el actual
        se muestra ya, si no queda cacheado para cuando rote)."""
        self._backdrops[key] = pix
        if self._items and self._items[self._index].key == key:
            self.backdrop.set_pixmap(pix)

    def item(self, key: str) -> CardData | None:
        for item in self._items:
            if item.key == key:
                return item
        return None

    def update_item(self, key: str, title: str | None, meta: str | None) -> bool:
        item = self.item(key)
        if item is None:
            return False
        if title is not None:
            item.title = title
        if meta is not None:
            item.meta = meta
        return True

    def refresh_current(self):
        """Redibuja los textos del ítem activo (tras actualizar sus datos)."""
        if self._items:
            self._apply_item(animate=False)

    def _rotate(self):
        if len(self._items) < 2:
            return
        self._index = (self._index + 1) % len(self._items)
        self._apply_item(animate=True)

    def _apply_item(self, animate: bool):
        item = self._items[self._index]
        self.hero_title.setText(item.title)
        self.hero_meta.setText(item.meta or "")
        payload = item.payload if isinstance(item.payload, dict) else {}
        synopsis = payload.get("synopsis", "")
        self.hero_synopsis.setText(synopsis)
        self.hero_synopsis.setVisible(bool(synopsis))
        self.backdrop.set_pixmap(self._backdrops.get(item.key))


class HomeView(QWidget):
    """Pantalla de inicio: hero + filas horizontales."""

    open_requested = Signal(str)          # abrir carpeta (navegación normal)
    play_requested = Signal(object)       # CardData (video)
    detail_requested = Signal(str)        # abrir vista detalle de carpeta
    refresh_requested = Signal()

    ROW_ORDER = ["continue", "movies", "series", "kids", "recent", "favorites"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: dict[str, CardRow] = {}
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 16, 0, 24)
        self.content_layout.setSpacing(18)

        self.hero = HeroBanner()
        self.hero.play_requested.connect(self.play_requested.emit)
        self.hero.info_requested.connect(self.detail_requested.emit)
        self.content_layout.addWidget(self.hero)

        self.loading_label = QLabel("Cargando catálogo…")
        self.loading_label.setObjectName("homeLoading")
        self.loading_label.setAlignment(Qt.AlignCenter)
        self.loading_label.setContentsMargins(0, 40, 0, 0)
        self.content_layout.addWidget(self.loading_label)

        self.rows_container = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_container)
        self.rows_layout.setContentsMargins(32, 0, 0, 0)
        self.rows_layout.setSpacing(4)
        self.content_layout.addWidget(self.rows_container)

        self.content_layout.addStretch(1)

    # ------------------------------------------------------------------
    def show_loading(self, text: str = "Cargando catálogo…"):
        self.loading_label.setText(text)
        self.loading_label.setVisible(True)

    def set_structure(self, rows: list[tuple[str, str, list[CardData]]], hero: list[CardData]):
        """rows: [(row_key, título, [CardData…])]; hero: ítems del banner."""
        self.loading_label.setVisible(False)
        self.hero.set_items(hero)

        wanted_keys = [key for key, _title, _cards in rows]
        # (re)crea filas respetando el orden conocido; las claves nuevas
        # quedan al final
        ordered = [k for k in self.ROW_ORDER if k in wanted_keys]
        ordered += [k for k in wanted_keys if k not in self.ROW_ORDER]
        by_key = {key: (key, title, cards) for key, title, cards in rows}

        existing = dict(self._rows)
        self._rows = {}
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()

        for key in ordered:
            _key, title, cards = by_key[key]
            row = existing.pop(key, None)
            if row is None:
                row = CardRow(title)
                row.activated.connect(self._on_card_activated)
                row.show_menu.connect(self._on_card_menu)
            row.set_cards(cards)
            row.show()
            self._rows[key] = row
            self.rows_layout.addWidget(row)
        for leftover in existing.values():
            leftover.deleteLater()

    # ------------------------------------------------------------------
    def _on_card_activated(self, key: str):
        data = self._find_card(key)
        if data is None:
            return
        if data.is_video:
            self.play_requested.emit(data)
        else:
            self.open_requested.emit(data.url)

    def _on_card_menu(self, data: CardData):
        # clic derecho: abrir la vista detalle (más opciones) en vez de
        # reproducir directo
        if data.is_video:
            self.play_requested.emit(data)
        else:
            self.detail_requested.emit(data.url)

    def _find_card(self, key: str) -> CardData | None:
        for row in self._rows.values():
            card = row.card(key)
            if card:
                return card.data
        return self.hero.item(key)

    # ------------------------------------------------------------------
    def set_poster(self, key: str, pix: QPixmap) -> bool:
        """Póster de tarjeta. Devuelve True si había una tarjeta con esa key."""
        for row in self._rows.values():
            card = row.card(key)
            if card:
                try:
                    card.set_poster(pix)
                except RuntimeError:
                    pass
                return True
        return False

    def set_backdrop(self, key: str, pix: QPixmap):
        self.hero.set_backdrop(key, pix)

    def update_card_meta(self, key: str, title: str | None = None, meta: str | None = None):
        matched = False
        for row in self._rows.values():
            if row.card(key):
                row.update_data(key, title, meta)
                matched = True
        if self.hero.update_item(key, title, meta):
            matched = True
        if matched:
            self.hero.refresh_current()
