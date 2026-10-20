"""
movie_detail.py
---------------
Vista de detalle estilo Netflix para una carpeta que "parece" una
película o serie: backdrop panorámico con scrim, póster, título,
chips de metadatos (año · duración · ★ rating · géneros), sinopsis,
botón(es) de reproducción y lista de episodios/videos.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QFrame, QStackedLayout, QSizePolicy,
)

import theme
from cards import rounded_pixmap
from home_view import BackdropLabel

HERO_HEIGHT = 320


class MovieDetailView(QWidget):
    """Emite play_requested(url, nombre) cuando el usuario elige reproducir,
    show_files_requested cuando quiere ver el listado crudo de archivos,
    e imdb_requested cuando pide (re)buscar la ficha en TMDb."""

    play_requested = Signal(str, str)
    show_files_requested = Signal()
    imdb_requested = Signal()

    POSTER_SIZE = (168, 252)         # póster dentro del hero

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        outer.addWidget(scroll, stretch=1)

        content = QWidget()
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 24)
        layout.setSpacing(0)

        # --- Hero: backdrop + póster + título + chips + botones ---------
        hero = QFrame()
        hero.setFixedHeight(HERO_HEIGHT)
        hero.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        hero_stack = QStackedLayout()
        hero_stack.setStackingMode(QStackedLayout.StackAll)

        self.backdrop_label = BackdropLabel()
        hero_stack.addWidget(self.backdrop_label)

        hero_content = QWidget()
        hero_content.setAttribute(Qt.WA_TranslucentBackground, True)
        hero_content.setAutoFillBackground(False)
        hero_layout = QHBoxLayout(hero_content)
        hero_layout.setContentsMargins(32, 24, 32, 24)
        hero_layout.setSpacing(24)

        self.poster_label = QLabel()
        self.poster_label.setFixedSize(*self.POSTER_SIZE)
        self.poster_label.setScaledContents(False)
        placeholder = QPixmap(*self.POSTER_SIZE)
        placeholder.fill(QColor(theme.SURFACE))
        self.poster_label.setPixmap(placeholder)
        hero_layout.addWidget(self.poster_label, alignment=Qt.AlignBottom)

        info_col = QVBoxLayout()
        info_col.setSpacing(8)

        def _no_bg(label):
            label.setAttribute(Qt.WA_TranslucentBackground, True)
            label.setAutoFillBackground(False)
            label.setStyleSheet("background: transparent;")
            return label

        self.title_label = _no_bg(QLabel(""))
        self.title_label.setObjectName("detailTitle")
        self.title_label.setWordWrap(True)
        info_col.addWidget(self.title_label)

        self.meta_label = _no_bg(QLabel(""))
        self.meta_label.setObjectName("detailMeta")
        info_col.addWidget(self.meta_label)

        self.chips_layout = QHBoxLayout()
        self.chips_layout.setSpacing(6)
        self.chips_layout.setContentsMargins(0, 2, 0, 2)
        info_col.addLayout(self.chips_layout)

        info_col.addSpacing(4)
        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.play_hero_btn = QPushButton("▶  Reproducir")
        self.play_hero_btn.setObjectName("playHeroBtn")
        self.play_hero_btn.setCursor(Qt.PointingHandCursor)
        self.play_hero_btn.hide()  # se muestra en set_videos cuando hay exactamente 1 video
        buttons.addWidget(self.play_hero_btn)
        self.tmdb_btn = QPushButton("⟳  Buscar ficha en TMDb")
        self.tmdb_btn.setObjectName("ghostBtn")
        self.tmdb_btn.setCursor(Qt.PointingHandCursor)
        self.tmdb_btn.setToolTip("Busca sinopsis en español, póster, año, género y rating en TMDb")
        self.tmdb_btn.clicked.connect(self.imdb_requested.emit)
        buttons.addWidget(self.tmdb_btn)
        buttons.addStretch(1)
        info_col.addLayout(buttons)

        info_col.addStretch(1)
        hero_layout.addLayout(info_col, stretch=1)
        hero_stack.addWidget(hero_content)
        hero.setLayout(hero_stack)
        layout.addWidget(hero)

        # --- Cuerpo: sinopsis + episodios + archivos --------------------
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(32, 20, 32, 0)
        body_layout.setSpacing(12)

        self.synopsis_label = QLabel("")
        self.synopsis_label.setObjectName("detailSynopsis")
        self.synopsis_label.setWordWrap(True)
        body_layout.addWidget(self.synopsis_label)

        body_layout.addSpacing(4)
        self.videos_header = QLabel("CONTENIDO")
        self.videos_header.setObjectName("sectionLabel")
        self.videos_header.hide()
        body_layout.addWidget(self.videos_header)

        self.play_buttons_layout = QVBoxLayout()
        self.play_buttons_layout.setSpacing(8)
        body_layout.addLayout(self.play_buttons_layout)

        self.files_btn = QPushButton("📁 Ver todos los archivos de la carpeta")
        self.files_btn.setObjectName("filesBtn")
        self.files_btn.setCursor(Qt.PointingHandCursor)
        self.files_btn.clicked.connect(self.show_files_requested.emit)
        body_layout.addWidget(self.files_btn, alignment=Qt.AlignLeft)

        layout.addWidget(body)

        self.play_hero_btn.clicked.connect(self._emit_first_video)
        self._videos: list[tuple[str, str]] = []

    def _emit_first_video(self):
        if self._videos:
            url, name = self._videos[0]
            self.play_requested.emit(url, name)

    # ------------------------------------------------------------------
    def reset(self, title: str):
        self.title_label.setText(title)
        self.meta_label.setText("")
        self.synopsis_label.setText("Buscando ficha…")
        placeholder = QPixmap(*self.POSTER_SIZE)
        placeholder.fill(QColor(theme.SURFACE))
        self.poster_label.setPixmap(placeholder)
        self.backdrop_label.set_pixmap(None)
        self.set_chips([])
        self._clear_play_buttons()
        self._videos = []
        self.play_hero_btn.hide()

    def _clear_play_buttons(self):
        while self.play_buttons_layout.count():
            item = self.play_buttons_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    # ------------------------------------------------------------------
    def set_meta(self, text: str):
        self.meta_label.setText(text)
        self.meta_label.setVisible(bool(text))

    def set_chips(self, chips: list[str]):
        """Chips de metadatos bajo el título. Los que parecen rating
        (empiezan con ★) usan un estilo especial."""
        while self.chips_layout.count():
            item = self.chips_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        for text in chips:
            chip = QLabel(text)
            chip.setObjectName("chipRating" if text.startswith("★") else "chip")
            self.chips_layout.addWidget(chip)
        self.chips_layout.addStretch(1)

    def set_synopsis(self, text: str):
        self.synopsis_label.setText(
            text.strip() if text and text.strip() else "Sin sinopsis disponible para este título."
        )

    def set_videos(self, videos: list[tuple[str, str]]):
        """videos: lista de (url, texto_del_botón). Con 1 solo video se
        muestra el botón hero grande; con varios, una lista de episodios."""
        self._videos = list(videos)
        self._clear_play_buttons()
        if not videos:
            self.videos_header.hide()
            self.play_hero_btn.hide()
            self.play_buttons_layout.addWidget(QLabel("No se encontró ningún video en esta carpeta."))
            return
        if len(videos) == 1:
            self.videos_header.hide()
            self.play_hero_btn.show()
            return
        self.videos_header.setText(f"CONTENIDO ({len(videos)})")
        self.videos_header.show()
        self.play_hero_btn.hide()
        for url, name in videos:
            btn = QPushButton(f"▶   {name}")
            btn.setObjectName("episodeBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked=False, u=url, n=name: self.play_requested.emit(u, n))
            self.play_buttons_layout.addWidget(btn)

    # ------------------------------------------------------------------
    def set_poster_pixmap(self, pixmap: QPixmap):
        """Pixmap ya escalado a POSTER_SIZE (se redondea acá)."""
        self.poster_label.setPixmap(rounded_pixmap(pixmap))

    def set_backdrop_pixmap(self, pixmap: QPixmap):
        self.backdrop_label.set_pixmap(pixmap)
