"""
main_window.py
--------------
Ventana principal de la app: navegación por el árbol de carpetas del
servidor, búsqueda, favoritos, historial, vista de grilla con carátulas,
descargas y panel de reproducción.
"""

from __future__ import annotations

import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse, unquote

from PySide6.QtCore import Qt, Signal, QObject, QTimer, QSize
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QLineEdit, QPushButton, QLabel, QStackedWidget, QMessageBox,
    QToolButton, QMenu, QFileDialog,
)

from apache_index import ApacheIndexClient, DirListing, Entry, friendly_error, subtitle_urls_for
from player import PlayerWidget, _fmt_time
from progress import ProgressStore
from thumbnails import (
    ThumbnailManager, candidate_urls_for,
    in_folder_poster_candidates, in_folder_backdrop_candidates,
    _looks_like_real_image, _revalidate_and_reencode,
)
from downloads import DownloadManager
from movie_detail import MovieDetailView
from music_view import MusicAlbumView, MusicPlayerBar, LyricsDialog, ALBUM_COVER_SIZE
from audio_metadata import AudioMetadataManager
from lyrics import fetch_lyrics
from config_store import ConfigStore
from online_dialogs import ApiKeyDialog, SubtitleSearchDialog, SearchTitleDialog
from local_subs_dialog import LocalSubsDialog
import tmdb
import theme
from naming import clean_display_title, episode_display, parse_year
from metadata import MetadataStore, MediaMeta, meta_from_tmdb_info, TitleOverrideStore
from cards import CardData, POSTER_SIZE as CARD_POSTER_SIZE
from home_view import HomeView
from history_view import HistoryView, COVER_SIZE as HISTORY_COVER_SIZE
from sitemap import SiteMap
from search_dialog import GlobalSearchDialog

APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "VisualesUCLV"
FAVORITES_FILE = APP_SUPPORT_DIR / "favorites.json"
PROGRESS_FILE = APP_SUPPORT_DIR / "progress.json"
CONFIG_FILE = APP_SUPPORT_DIR / "config.json"
METADATA_CACHE_FILE = APP_SUPPORT_DIR / "metadata_cache.json"
TITLE_OVERRIDE_FILE = APP_SUPPORT_DIR / "title_overrides.json"
THUMBNAILS_DIR = APP_SUPPORT_DIR / "thumbnails_v2"  # v2: caché re-validada con Pillow (ver thumbnails.py)
DOWNLOADS_DIR = Path.home() / "Downloads" / "VisualesUCLV"
PROGRESS_SAVE_INTERVAL_MS = 5000
HOME_STALE_SECONDS = 300  # el home se refresca solo si tiene más de 5 min

BASE_URL = "https://visuales.uclv.cu/"

# Tamaños con los que se cachean las imágenes grandes (backdrops). Qt
# escala después desde estos tamaños al redibujar.
BACKDROP_SIZE = QSize(1280, 720)

# Accesos directos a las carpetas principales del sitio, mostrados en el
# sidebar. El segundo valor debe coincidir EXACTO con el nombre de la
# carpeta en el servidor (sensible a mayúsculas en muchos servidores Apache).
CATEGORY_SHORTCUTS = [
    ("🎬  Películas", "Peliculas"),
    ("📺  Series", "Series"),
    ("🧸  Infantiles", "Infantiles"),
]

FOLDER_ICON = "📁"
VIDEO_ICON = "🎬"
FILE_ICON = "📄"

GRID_ICON_SIZE = QSize(120, 170)
GRID_CELL_SIZE = QSize(148, 220)


def _fetch_text_bg(session, url: str) -> tuple[str, str]:
    """Descarga un archivo de texto (ej. sinopsis.txt). Corre en un hilo
    común (ThreadPoolExecutor), NO en un QThread — ver nota más abajo
    sobre por qué se cambió."""
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        # Muchos de estos archivos vienen en Latin-1/CP1252 en vez de
        # UTF-8 (típico de servidores viejos), así que probamos UTF-8
        # primero y si falla, caemos a Latin-1 en vez de mostrar texto
        # corrupto con tildes rotas.
        try:
            text = resp.content.decode("utf-8")
        except UnicodeDecodeError:
            text = resp.content.decode("latin-1", errors="replace")
        return text, ""
    except Exception as exc:
        return "", str(exc)


def _clean_title(name: str) -> str:
    """Nombre de carpeta (URL-encoded) -> título legible."""
    name = unquote(name)
    name = name.replace(".", " ").replace("_", " ").strip()
    return " ".join(name.split())


def _parse_size_to_bytes(size_str: str) -> float:
    """Convierte tamaños como "350M", "2.1G", "45K" a bytes (estimado,
    ya que el listado de Apache no da bytes exactos)."""
    size_str = (size_str or "").strip()
    if not size_str or size_str == "-":
        return 0.0
    try:
        unit = size_str[-1].upper()
        mult = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}.get(unit)
        if mult:
            return float(size_str[:-1]) * mult
        return float(size_str)
    except (ValueError, IndexError):
        return 0.0


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# NOTA sobre el cambio de arquitectura de hilos (si estás leyendo esto
# porque algo volvió a crashear): antes, los listados y la sinopsis se
# bajaban con el patrón QThread + moveToThread + worker.run() conectado
# a thread.started. Ese patrón causaba crashes nativos intermitentes en
# macOS (excepciones NSException sin atajar, en medio de la maquinaria
# de PySide para invocar métodos Python desde el hilo de un QThread).
# El patrón que SÍ viene siendo estable en esta app (thumbnails.py,
# downloads.py) es más simple: hilos comunes de Python (vía
# ThreadPoolExecutor) que llaman directamente a `alguna_señal.emit(...)`
# desde el hilo de fondo. Qt detecta automáticamente que el emisor está
# en otro hilo y encola la llamada al slot de forma segura en el hilo
# principal — sin necesitar QThread para nada. navigate_to() y
# _fetch_synopsis() se migraron a este mismo patrón por eso.


def _make_placeholder(entry: Entry) -> QPixmap:
    """Carátula genérica mientras se busca/descarga la real (o si no hay)."""
    pix = QPixmap(GRID_ICON_SIZE)
    pix.fill(QColor(theme.SURFACE) if entry.is_dir else QColor(theme.SURFACE_ALT))
    painter = QPainter(pix)
    painter.setPen(QColor(theme.GLYPH_DIM))
    font = QFont()
    font.setPointSize(30)
    painter.setFont(font)
    glyph = "📁" if entry.is_dir else ("🎬" if entry.is_video else "📄")
    painter.drawText(pix.rect(), Qt.AlignCenter, glyph)
    painter.end()
    return pix


class _ClickableLabel(QLabel):
    """QLabel que emite clicked() al soltar el botón izquierdo."""

    clicked = Signal()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    # Señales propias para recibir resultados de trabajo en segundo plano
    # (ver la nota más arriba sobre por qué no se usa QThread para esto).
    _listing_ready_signal = Signal(object, bool, int)  # (DirListing, push_history, request_id)
    _synopsis_ready_signal = Signal(str, str, int)  # (texto, error, request_id)
    _lyrics_ready_signal = Signal(str, str)        # (letra, error)
    _imdb_ready_signal = Signal(object, str, str, int)  # (info dict|None, error, folder_url, request_id)
    _folder_scan_ready_signal = Signal(list, str, float)  # (archivos, nombre_raiz, bytes_totales)
    _add_subtitle_signal = Signal(str, str, bool)  # (url_video, url_subtitulo, seleccionar)
    _folder_subs_ready_signal = Signal(str, list, str)  # (url_video, entradas_subs, error)
    _home_ready_signal = Signal(object)           # (estructura de filas/hero del home)
    _meta_ready_signal = Signal(str, object)      # (folder_url, MediaMeta enriquecido)
    _sitemap_ready_signal = Signal()              # árbol listo para buscar

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Visuales UCLV")
        self.resize(1220, 780)

        self.client = ApacheIndexClient(BASE_URL)
        # Árbol de carpetas del sitio (listado.html que publica el
        # servidor): evita escanear carpeta por carpeta para el home.
        self.sitemap = SiteMap(
            BASE_URL, APP_SUPPORT_DIR / "sitemap.json", session=self.client.session
        )
        self.history: list[str] = []
        self.history_pos = -1
        self.current_entries: list[Entry] = []
        self.current_url: str | None = None
        self._pending_retry_url: str | None = None
        self._detail_entries: list[Entry] = []
        self._detail_folder_url: str | None = None
        self._detail_poster_key: str | None = None
        self._detail_media_type: str = "movie"
        self._grid_items: dict[str, QListWidgetItem] = {}
        self.view_mode = "list"  # "list" | "grid"
        self._io_executor = ThreadPoolExecutor(max_workers=4)
        # IDs para descartar respuestas viejas que llegan tarde (el usuario
        # ya navegó a otra carpeta o ya se mostró otra sinopsis).
        self._listing_request_id = 0
        self._synopsis_request_id = 0
        self._imdb_request_id = 0
        # True si la búsqueda de TMDb la pidió el usuario a mano (y no la
        # búsqueda automática al abrir la carpeta): solo en ese caso le
        # ofrecemos corregir el nombre si no se encontró nada.
        self._imdb_manual_request = False
        self._music_cover_set = False

        self._listing_ready_signal.connect(self._on_listing_ready)
        self._synopsis_ready_signal.connect(self._on_synopsis_ready)
        self._lyrics_ready_signal.connect(self._on_lyrics_ready)
        self._active_lyrics_dialog = None
        self._imdb_ready_signal.connect(self._on_imdb_ready)
        self._folder_scan_ready_signal.connect(self._on_folder_scan_ready)
        self._add_subtitle_signal.connect(self._on_history_subtitle_ready)
        self._folder_subs_ready_signal.connect(self._on_folder_subs_ready)

        APP_SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
        self.favorites = self._load_favorites()
        self.progress = ProgressStore(PROGRESS_FILE)
        self.thumbnails = ThumbnailManager(self.client.session, THUMBNAILS_DIR)
        self.thumbnails.thumbnail_ready.connect(self._on_thumbnail_ready)
        self.downloads = DownloadManager(self.client.session, DOWNLOADS_DIR)
        self.downloads.progress.connect(self._on_download_progress)
        self.downloads.status_changed.connect(self._on_download_status)
        self._download_labels: dict[str, str] = {}
        self.audio_metadata = AudioMetadataManager(self.client.session)
        self.audio_metadata.metadata_ready.connect(self._on_track_metadata_ready)
        self._music_folder_poster_key: str | None = None
        self.config = ConfigStore(CONFIG_FILE)
        self.meta_store = MetadataStore(METADATA_CACHE_FILE)
        # Títulos corregidos a mano por el usuario (carpetas con el
        # nombre mal escrito) para la búsqueda en TMDb.
        self.title_overrides = TitleOverrideStore(TITLE_OVERRIDE_FILE)
        self._home_built_at = 0.0
        self._active_search_dialog: GlobalSearchDialog | None = None
        self._sitemap_loading = False
        self._pending_fav_scroll = False

        self._home_ready_signal.connect(self._on_home_ready)
        self._meta_ready_signal.connect(self._on_meta_ready)
        self._sitemap_ready_signal.connect(self._on_sitemap_ready)

        self._build_ui()

        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(PROGRESS_SAVE_INTERVAL_MS)
        self._progress_timer.timeout.connect(self._save_current_progress)
        self._progress_timer.start()

        self._show_home()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # --- Barra superior estilo streaming ------------------------------
        # Sin sidebar: la navegación principal vive acá (menú "Explorar",
        # buscador e íconos), así las filas de tarjetas ganan todo el ancho.
        topbar = QWidget()
        topbar.setObjectName("topbar")
        topbar_layout = QHBoxLayout(topbar)
        topbar_layout.setContentsMargins(22, 12, 22, 12)
        topbar_layout.setSpacing(12)

        logo = _ClickableLabel("VISUALES UCLV")
        logo.setObjectName("logo")
        logo.setCursor(Qt.PointingHandCursor)
        logo.setToolTip("Ir a Inicio")
        logo.clicked.connect(self._show_home)
        topbar_layout.addWidget(logo)
        topbar_layout.addSpacing(8)

        # Menú desplegable "Explorar ▾" (Favoritos + categorías + historial).
        # Inicio ya no está acá: se llega haciendo clic en el logo.
        self.explore_btn = QToolButton()
        self.explore_btn.setObjectName("exploreBtn")
        self.explore_btn.setText("Explorar ▾")
        self.explore_btn.setPopupMode(QToolButton.InstantPopup)
        self.explore_btn.setToolTip("Navegar por el catálogo")
        explore_menu = QMenu(self.explore_btn)
        explore_menu.addAction("⭐  Favoritos", self._show_favorites)
        explore_menu.addAction("🕐  Historial", self._show_history)
        explore_menu.addSeparator()
        for label, folder in CATEGORY_SHORTCUTS:
            explore_menu.addAction(
                label,
                lambda checked=False, f=folder: self.navigate_to(
                    BASE_URL + f + "/", push_history=True
                ),
            )
        self.explore_btn.setMenu(explore_menu)
        topbar_layout.addWidget(self.explore_btn)

        topbar_layout.addStretch(1)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Filtrar acá, o Enter para buscar en todo el sitio…")
        self.search_box.textChanged.connect(self._apply_filter)
        self.search_box.returnPressed.connect(self._on_global_search_requested)
        self.search_box.setFixedWidth(300)
        topbar_layout.addWidget(self.search_box)

        self.global_search_btn = QToolButton()
        self.global_search_btn.setText("🔍")
        self.global_search_btn.setToolTip("Buscar en todo el servidor (no solo esta carpeta)")
        self.global_search_btn.clicked.connect(self._on_global_search_requested)
        topbar_layout.addWidget(self.global_search_btn)

        self.view_toggle_btn = QPushButton("🖼 Vista grilla")
        self.view_toggle_btn.setCheckable(True)
        self.view_toggle_btn.setToolTip(
            "La vista de grilla descarga carátulas — puede usar más datos"
        )
        self.view_toggle_btn.clicked.connect(self._toggle_view_mode)
        topbar_layout.addWidget(self.view_toggle_btn)

        # Íconos con desplegable: "en curso" (favorito) y descargas
        self.fav_btn = QToolButton()
        self.fav_btn.setObjectName("iconBtn")
        self.fav_btn.setText("☆")
        self.fav_btn.setToolTip("Marcar/desmarcar esta carpeta como favorita")
        self.fav_btn.setPopupMode(QToolButton.InstantPopup)
        self.fav_menu = QMenu(self.fav_btn)
        self.fav_menu.aboutToShow.connect(self._rebuild_fav_menu)
        self.fav_btn.setMenu(self.fav_menu)
        topbar_layout.addWidget(self.fav_btn)

        self.downloads_btn = QToolButton()
        self.downloads_btn.setObjectName("iconBtn")
        self.downloads_btn.setText("⬇")
        self.downloads_btn.setToolTip("Descargas")
        self.downloads_btn.setPopupMode(QToolButton.InstantPopup)
        self.dl_menu = QMenu(self.downloads_btn)
        self.dl_menu.aboutToShow.connect(self._rebuild_downloads_menu)
        self.downloads_btn.setMenu(self.dl_menu)
        topbar_layout.addWidget(self.downloads_btn)

        root_layout.addWidget(topbar)

        # --- Panel principal ----------------------------------------------
        main_panel = QWidget()
        main_layout = QVBoxLayout(main_panel)
        main_layout.setContentsMargins(20, 12, 20, 16)
        main_layout.setSpacing(10)

        # Fila de navegación (atrás/adelante/refrescar + breadcrumb),
        # visible sobre todo cuando estás explorando carpetas.
        nav_row = QHBoxLayout()
        self.back_btn = QToolButton()
        self.back_btn.setText("◀")
        self.back_btn.setToolTip("Atrás")
        self.back_btn.clicked.connect(self.go_back)
        self.fwd_btn = QToolButton()
        self.fwd_btn.setText("▶")
        self.fwd_btn.setToolTip("Adelante")
        self.fwd_btn.clicked.connect(self.go_forward)
        self.refresh_btn = QToolButton()
        self.refresh_btn.setText("⟳")
        self.refresh_btn.setToolTip("Refrescar")
        self.refresh_btn.clicked.connect(self.refresh_current)

        self.breadcrumb = QLabel("")
        self.breadcrumb.setObjectName("breadcrumb")
        self.breadcrumb.setWordWrap(True)

        nav_row.addWidget(self.back_btn)
        nav_row.addWidget(self.fwd_btn)
        nav_row.addWidget(self.refresh_btn)
        nav_row.addSpacing(10)
        nav_row.addWidget(self.breadcrumb, stretch=1)
        main_layout.addLayout(nav_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        main_layout.addWidget(self.status_label)

        # Vista de listado / reproductor apilados
        self.stack = QStackedWidget()

        self.file_list = QListWidget()
        self.file_list.setObjectName("fileList")
        self.file_list.itemActivated.connect(self._on_item_activated)
        self.file_list.setSpacing(2)
        self.file_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self._show_file_menu)
        self.stack.addWidget(self.file_list)

        self.player = PlayerWidget()
        self.player.error_occurred.connect(self._show_error)
        self.player.track_finished.connect(self._on_video_finished)
        self.player.online_subtitles_requested.connect(self._on_online_subtitles_requested)
        self.player.folder_subtitles_requested.connect(self._on_pick_folder_subs)
        self.stack.addWidget(self.player)

        self.detail_view = MovieDetailView()
        self.detail_view.play_requested.connect(self._on_detail_play_requested)
        self.detail_view.show_files_requested.connect(self._show_raw_file_list)
        self.detail_view.imdb_requested.connect(self._on_imdb_requested)
        self.detail_view.edit_title_requested.connect(self._on_edit_title_requested)
        self.stack.addWidget(self.detail_view)

        self.music_view = MusicAlbumView()
        self.music_view.play_requested.connect(self._on_music_play_requested)
        self.stack.addWidget(self.music_view)

        self.history_view = HistoryView()
        self.history_view.play_requested.connect(self._on_history_play_requested)
        self.history_view.remove_requested.connect(self._on_history_remove_requested)
        self.stack.addWidget(self.history_view)

        # Pantalla de inicio estilo streaming: hero + filas horizontales
        self.home_view = HomeView()
        self.home_view.open_requested.connect(lambda url: self.navigate_to(url, push_history=True))
        self.home_view.detail_requested.connect(lambda url: self.navigate_to(url, push_history=True))
        self.home_view.play_requested.connect(self._on_home_play)
        self.stack.addWidget(self.home_view)

        main_layout.addWidget(self.stack, stretch=1)

        # Barra de reproducción actual (para volver de la vista de video)
        self.close_player_btn = QPushButton("⬅ Volver al explorador")
        self.close_player_btn.clicked.connect(self._close_player)
        self.close_player_btn.hide()
        main_layout.addWidget(self.close_player_btn)

        # Barra de música persistente: se mantiene visible sin importar
        # qué carpeta estés mirando (como la barra inferior de Spotify).
        self.music_bar = MusicPlayerBar()
        self.music_bar.lyrics_requested.connect(self._on_lyrics_requested)
        main_layout.addWidget(self.music_bar)

        root_layout.addWidget(main_panel, stretch=1)
        self.setCentralWidget(root)

    # ------------------------------------------------------------------
    # Navegación
    # ------------------------------------------------------------------
    def navigate_to(self, url: str, push_history: bool, force: bool = False):
        self._listing_request_id += 1
        request_id = self._listing_request_id
        self.status_label.setText("Cargando…")
        self.file_list.clear()
        self._grid_items.clear()
        try:
            self._io_executor.submit(self._fetch_listing_bg, url, force, push_history, request_id)
        except RuntimeError:
            pass  # la app se está cerrando; ignoramos trabajo nuevo

    def _fetch_listing_bg(self, url: str, force: bool, push_history: bool, request_id: int):
        """Corre en un hilo del executor. Emitir la señal acá (desde un
        hilo que no es el principal) es seguro: Qt encola automáticamente
        la entrega al slot conectado en el hilo principal."""
        listing = self.client.list_dir(url, force=force)
        self._listing_ready_signal.emit(listing, push_history, request_id)

    def _on_listing_ready(self, listing: DirListing, push_history: bool, request_id: int = -1):
        if request_id != -1 and request_id != self._listing_request_id:
            return  # respuesta vieja: el usuario ya pidió otra carpeta
        if listing.error:
            self.status_label.setText(friendly_error(listing.error))
            self.file_list.clear()
            self.current_entries = []
            self.current_url = listing.url
            self._grid_items.clear()
            retry_item = QListWidgetItem("⟳  Tocá para reintentar")
            retry_item.setData(Qt.UserRole, None)
            self.file_list.addItem(retry_item)
            self.stack.setCurrentWidget(self.file_list)
            self._pending_retry_url = listing.url
            return

        self.current_url = listing.url
        self.current_entries = listing.entries
        self.status_label.setText(f"{len(listing.entries)} elementos")

        if push_history:
            # Descarta "adelante" si navegamos a algo nuevo
            self.history = self.history[: self.history_pos + 1]
            self.history.append(listing.url)
            self.history_pos = len(self.history) - 1

        self._update_breadcrumb(listing.url)
        self._update_fav_button()
        self.close_player_btn.hide()

        if self._looks_like_movie_folder(listing.entries, listing.url):
            self._show_movie_detail(listing.entries, listing.url)
        elif self._looks_like_music_folder(listing.entries, listing.url):
            self._show_music_album(listing.entries, listing.url)
        else:
            self._populate_list(listing.entries)
            self.stack.setCurrentWidget(self.file_list)

    # ------------------------------------------------------------------
    # Vista de detalle estilo Netflix
    # ------------------------------------------------------------------
    def _looks_like_movie_folder(self, entries: list[Entry], folder_url: str) -> bool:
        has_video = any(e.is_video for e in entries)
        if not has_video:
            return False
        has_sinopsis = any(e.name.lower() == "sinopsis.txt" for e in entries if not e.is_dir)
        # Todo lo que esté dentro de una carpeta "Peliculas" o "Series"
        # (con o sin tilde, en cualquier nivel de la ruta) se trata
        # directamente con la vista de detalle, tenga o no sinopsis.txt —
        # más confiable que depender de que todas tengan ese archivo.
        path_lower = unquote(urlparse(folder_url).path).lower().replace("í", "i")
        under_peliculas = "/peliculas" in path_lower
        under_series = "/series" in path_lower
        if has_sinopsis or under_peliculas or under_series:
            return True
        # Carpeta "hoja": tiene videos y ninguna subcarpeta propia de un
        # nivel más de navegación (ignoramos carpetas técnicas típicas de
        # releases). Esas son listados de episodios/película sueltos y se
        # ven mucho mejor en la vista de detalle que como carpetas crudas.
        IGNORED_DIRS = {"subs", "subtitles", "subtitulos", "subtítulos", "extras",
                        "sample", "samples", "artwork", "backdrops", "posters"}
        subdirs = [e for e in entries if e.is_dir and e.name.lower() not in IGNORED_DIRS]
        if not subdirs:
            return True
        return False

    def _media_type_for_folder(self, folder_url: str) -> str:
        """"movie" o "tv" — decide qué endpoint de TMDb usar."""
        path_lower = urlparse(folder_url).path.lower()
        if "/series" in path_lower:
            return "tv"
        # Carpetas de series fuera de /Series (p. ej. Recientes/CIA.S02)
        name = unquote(path_lower).rstrip("/").rsplit("/", 1)[-1]
        if re.search(r"(?:^|[.\s_-])s\d{1,2}(?:$|[.\s_-])|season|temporada", name):
            return "tv"
        return "movie"

    _SEASON_NAME_RE = re.compile(r"^(temporada|season|t\d+|s\d+)\b", re.IGNORECASE)

    def _series_root_url(self, folder_url: str) -> str:
        """Para una carpeta de temporada (Serie/Season 1/) devuelve la
        carpeta de la serie (Serie/); para todo lo demás, la misma URL.
        Así una corrección de nombre vale para todas las temporadas."""
        if self._detail_media_type != "tv":
            return folder_url
        parts = [p for p in urlparse(folder_url).path.split("/") if p]
        if not parts or not self._SEASON_NAME_RE.match(parts[-1].strip()):
            return folder_url
        parent = "/".join(parts[:-1])
        return BASE_URL.rstrip("/") + "/" + parent + "/"

    def _search_title_for_detail(self, folder_url: str, displayed_title: str) -> str:
        """Nombre con el que buscar en TMDb.

        Prioridad:
        1. El título corregido a mano por el usuario (carpetas con el
           nombre mal escrito, ej. "The mandalorian X1"). Para carpetas
           de temporada, vale la corrección hecha sobre la serie.
        2. Para series organizadas como Serie/Temporada 1/, la carpeta
           padre (el nombre de la temporada no es el de la serie).
        3. El título mostrado."""
        override = (
            self.title_overrides.get(folder_url)
            or self.title_overrides.get(self._series_root_url(folder_url))
        )
        if override:
            return override
        if self._detail_media_type != "tv":
            return displayed_title
        if self._SEASON_NAME_RE.match(displayed_title.strip()):
            parts = [p for p in urlparse(folder_url).path.split("/") if p]
            if len(parts) >= 2:
                return _clean_title(parts[-2])
        return displayed_title

    def _looks_like_music_folder(self, entries: list[Entry], folder_url: str) -> bool:
        has_audio = any(e.is_audio for e in entries)
        if not has_audio:
            return False
        path_lower = urlparse(folder_url).path.lower()
        return "/mp3s" in path_lower or "/mp3" in path_lower

    def _show_movie_detail(self, entries: list[Entry], folder_url: str):
        video_entries = [e for e in entries if e.is_video]
        folder_name = [p for p in urlparse(folder_url).path.split("/") if p][-1] if folder_url.strip("/") else ""
        title = clean_display_title(folder_name) or "Sin título"

        self._detail_media_type = self._media_type_for_folder(folder_url)
        self.detail_view.reset(title)
        # una búsqueda de TMDb de la carpeta anterior ya no aplica acá
        self._imdb_request_id += 1
        self._detail_entries = entries
        self._detail_folder_url = folder_url

        # Chips locales (sin red): año parseado del nombre + tamaño.
        # Se completan con la ficha de TMDb si está cacheada o llega ahora.
        chips: list[str] = []
        year = parse_year(folder_name)
        if year:
            chips.append(year)
        if len(video_entries) == 1 and video_entries[0].size:
            chips.append(video_entries[0].size)
        self.detail_view.set_chips(chips)

        # Videos con nombres limpios (episodios "T1 · E5 …") y % visto
        videos = []
        for e in video_entries:
            if self._detail_media_type == "tv":
                label = episode_display(e.name)
            else:
                label = clean_display_title(e.name) or e.name
            frac = self.progress.fraction(e.url)
            if frac is not None:
                label += "   ✓ visto" if frac >= 0.95 else f"   ▶ {int(frac * 100)}%"
            videos.append((e.url, label))
        self.detail_view.set_videos(videos)
        self.stack.setCurrentWidget(self.detail_view)

        # Sinopsis local (sinopsis.txt) en un hilo aparte
        sinopsis_entry = next((e for e in entries if e.name.lower() == "sinopsis.txt"), None)
        if sinopsis_entry:
            self._fetch_synopsis(sinopsis_entry.url)
        else:
            # invalida cualquier sinopsis anterior que todavía esté en vuelo
            self._synopsis_request_id += 1
            self.detail_view.set_synopsis("")

        # Carátula (heurística de imágenes dentro de la carpeta)
        self._detail_poster_key = folder_url + "#poster"
        self.thumbnails.request(self._detail_poster_key, in_folder_poster_candidates(entries))

        # Backdrop panorámico: fanart local dentro de la carpeta, y si hay
        # ficha cacheada de TMDb también su backdrop (el primero que
        # llegue gana; thumbnails cachea cada key por separado).
        backdrop_candidates = in_folder_backdrop_candidates(entries)
        stored = self.meta_store.get(folder_url)
        if stored:
            if stored.backdrop_url:
                backdrop_candidates.append(stored.backdrop_url)
            self._apply_meta_to_detail(stored)
        if backdrop_candidates:
            self.thumbnails.request(folder_url + "#backdrop", backdrop_candidates)

        # Ficha TMDb automática si hay API key y todavía no hay caché
        if stored is None:
            self._auto_fetch_tmdb(folder_url, title)

    def _auto_fetch_tmdb(self, folder_url: str, displayed_title: str):
        """Busca la ficha completa en TMDb sin mostrar diálogo — solo si
        ya hay una API key configurada (no se pide acá)."""
        api_key = self.config.get("tmdb_api_key")
        if not api_key:
            if not any(e.name.lower() == "sinopsis.txt" for e in self._detail_entries):
                self.detail_view.set_synopsis(
                    "Sin sinopsis local — tocá «Buscar ficha en TMDb» para "
                    "configurar una API key gratuita y ver sinopsis, póster, "
                    "géneros y rating."
                )
            return
        search_title = self._search_title_for_detail(folder_url, displayed_title)
        match = re.search(r"\((\d{4})\)\s*$", search_title)
        year = match.group(1) if match else None
        clean_title = re.sub(r"\s*\(\d{4}\)\s*$", "", search_title).strip()
        self._imdb_request_id += 1
        self._imdb_manual_request = False
        try:
            self._io_executor.submit(
                self._fetch_imdb_bg, api_key, clean_title, year,
                self._detail_media_type, self._imdb_request_id, folder_url,
            )
        except RuntimeError:
            pass  # la app se está cerrando

    def _fetch_synopsis(self, url: str):
        self._synopsis_request_id += 1
        request_id = self._synopsis_request_id
        try:
            self._io_executor.submit(self._fetch_synopsis_bg, url, request_id)
        except RuntimeError:
            pass  # la app se está cerrando; ignoramos trabajo nuevo

    def _fetch_synopsis_bg(self, url: str, request_id: int):
        text, error = _fetch_text_bg(self.client.session, url)
        self._synopsis_ready_signal.emit(text, error, request_id)

    def _on_synopsis_ready(self, text: str, error: str, request_id: int = -1):
        if request_id != -1 and request_id != self._synopsis_request_id:
            return  # llegó tarde: ya se está mostrando otra carpeta
        self.detail_view.set_synopsis(text if not error else "")

    def _on_detail_play_requested(self, url: str, name: str):
        entry = next((e for e in self._detail_entries if e.url == url), None)
        if entry:
            self._play_video_with_sub_popup(entry, self._detail_entries)
        else:
            self._open_player_with_resume(url, name, subtitle_urls=[])

    def _play_video_with_sub_popup(self, entry: Entry, siblings: list[Entry]):
        """Abre el video mostrando antes un pop-up con TODOS los
        subtítulos de la carpeta: los nombres no siempre coinciden con el
        del video y la carga automática no los encuentra, así que se deja
        que el usuario elija. Si cancela el pop-up, se usan los que
        emparejan solos (comportamiento anterior)."""
        auto_subs = subtitle_urls_for(entry, siblings)
        folder_subs = [e for e in siblings if e.is_subtitle]
        chosen = auto_subs
        if folder_subs:
            picked = self._ask_local_subs(entry.name, folder_subs, auto_subs)
            if picked is not None:
                chosen = picked
        self._open_player_with_resume(entry.url, entry.name, subtitle_urls=chosen)

    def _ask_local_subs(
        self, video_name: str,
        folder_subs: list[Entry], preselect: list[str],
    ) -> list[str] | None:
        """Muestra el pop-up de subtítulos locales. Devuelve las URLs
        elegidas, [] si eligió "sin subtítulos", o None si canceló."""
        dlg = LocalSubsDialog(
            video_name,
            [{"url": s.url, "name": s.name} for s in folder_subs],
            preselect=preselect,
            parent=self,
        )
        dlg.exec()
        return dlg.chosen

    def _on_pick_folder_subs(self):
        """Botón del reproductor: elegir subtítulos de la carpeta del
        video que se está reproduciendo ahora mismo."""
        video_url = self.player.current_url
        if not video_url:
            return
        subs = self._folder_subtitles_cached(video_url)
        if subs:
            self._apply_subs_choice(video_url, subs)
            return
        # No tenemos el listado a mano (ej. vino del historial): lo
        # buscamos en segundo plano y avisamos por señal.
        try:
            self._io_executor.submit(self._fetch_folder_subs_bg, video_url)
        except RuntimeError:
            pass

    def _folder_subtitles_cached(self, video_url: str) -> list[Entry]:
        """Subtítulos de la carpeta del video, si el listado está en
        memoria (vista de detalle o carpeta actual)."""
        folder_url = video_url.rsplit("/", 1)[0] + "/"
        if self._detail_folder_url == folder_url and self._detail_entries:
            entries = self._detail_entries
        elif self.current_url == folder_url and self.current_entries:
            entries = self.current_entries
        else:
            return []
        return [e for e in entries if e.is_subtitle]

    def _fetch_folder_subs_bg(self, video_url: str):
        folder_url = video_url.rsplit("/", 1)[0] + "/"
        listing = self.client.list_dir(folder_url)  # cacheado en la mayoría de los casos
        subs = [e for e in listing.entries if e.is_subtitle] if not listing.error else []
        self._folder_subs_ready_signal.emit(video_url, subs, listing.error)

    def _on_folder_subs_ready(self, video_url: str, subs: list[Entry], error: str):
        if self.player.current_url != video_url:
            return  # ya se cerró el player o cambió de video
        if error:
            self._show_error(f"No se pudo listar la carpeta del video: {error}")
            return
        if not subs:
            QMessageBox.information(
                self, "Subtítulos",
                "No hay archivos de subtítulo en la misma carpeta que este video.\n"
                "Probá con 🌐 Subtítulos (OpenSubtitles) o descargá uno.",
            )
            return
        self._apply_subs_choice(video_url, subs)

    def _apply_subs_choice(self, video_url: str, folder_subs: list[Entry]):
        video_name = video_url.rsplit("/", 1)[-1]
        entry = next(
            (e for e in (self._detail_entries + self.current_entries) if e.url == video_url),
            None,
        )
        preselect = subtitle_urls_for(entry, folder_subs) if entry else []
        chosen = self._ask_local_subs(video_name, folder_subs, preselect)
        if chosen is None:
            return  # canceló: no tocamos lo que ya se está reproduciendo
        # Reemplaza (no suma) para no repetir subtítulos si ya había
        # algunos cargados de la carga automática.
        self.player.replace_subtitles(chosen)

    def _show_raw_file_list(self):
        self._populate_list(self.current_entries)
        self.stack.setCurrentWidget(self.file_list)

    # ------------------------------------------------------------------
    # Vista de música (carpetas bajo /MP3s/)
    # ------------------------------------------------------------------
    def _show_music_album(self, entries: list[Entry], folder_url: str):
        title = _clean_title(
            [p for p in urlparse(folder_url).path.split("/") if p][-1] if folder_url.strip("/") else ""
        )
        self.music_view.load(entries, title or "Sin título")
        self.stack.setCurrentWidget(self.music_view)
        self._music_cover_set = False

        # Carátula de la carpeta como respaldo inmediato mientras llegan
        # las carátulas embebidas de cada track.
        self._music_folder_poster_key = folder_url + "#musiccover"
        self.thumbnails.request(self._music_folder_poster_key, in_folder_poster_candidates(entries))

        # Metadatos (título/artista/carátula embebida) de cada track, en
        # segundo plano — se van completando fila por fila.
        for entry in entries:
            if entry.is_audio:
                self.audio_metadata.request(entry)

    def _on_track_metadata_ready(self, url: str, track):
        self.music_view.update_track_meta(url, track)
        # si la carpeta no tenía una carátula suelta, usamos la primera
        # carátula embebida que llegue como carátula del álbum. Ojo: el
        # QLabel arranca con un placeholder no nulo, así que "está vacío"
        # no sirve como condición — usamos una bandera explícita.
        if (
            track.cover_bytes
            and self.stack.currentWidget() is self.music_view
            and not self._music_cover_set
        ):
            pix = QPixmap()
            if pix.loadFromData(track.cover_bytes):
                scaled = pix.scaled(
                    ALBUM_COVER_SIZE[0], ALBUM_COVER_SIZE[1],
                    Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
                )
                self.music_view.set_cover_pixmap(scaled)
                self._music_cover_set = True

    def _on_music_play_requested(self, tracks: list, start_index: int, shuffle: bool):
        self.music_bar.play_queue(tracks, start_index=start_index, shuffle=shuffle)

    def _on_lyrics_requested(self, artist: str, title: str):
        dlg = LyricsDialog(artist, title, self)
        dlg.show()
        self._active_lyrics_dialog = dlg
        try:
            self._io_executor.submit(self._fetch_lyrics_bg, artist, title)
        except RuntimeError:
            pass

    def _fetch_lyrics_bg(self, artist: str, title: str):
        text, error = fetch_lyrics(artist, title)
        self._lyrics_ready_signal.emit(text, error)

    def _on_lyrics_ready(self, text: str, error: str):
        dlg = self._active_lyrics_dialog
        if dlg is None:
            return
        try:
            dlg.set_text(text if not error else error)
        except RuntimeError:
            pass  # el usuario ya cerró el diálogo

    # ------------------------------------------------------------------
    # IMDb (vía OMDb) y subtítulos online (vía OpenSubtitles)
    # ------------------------------------------------------------------
    def _ensure_api_key(self, config_key: str, service_name: str, signup_url: str, instructions: str) -> str | None:
        """Devuelve la API key guardada, o pide una nueva con un diálogo
        si todavía no hay ninguna guardada. None si el usuario cancela."""
        key = self.config.get(config_key)
        if key:
            return key
        dlg = ApiKeyDialog(service_name, signup_url, instructions, self)
        if dlg.exec() == ApiKeyDialog.Accepted and dlg.api_key:
            self.config.set(config_key, dlg.api_key)
            return dlg.api_key
        return None

    def _on_imdb_requested(self):
        api_key = self._ensure_api_key(
            "tmdb_api_key", "TMDb",
            "https://www.themoviedb.org/settings/api",
            "Para buscar sinopsis EN ESPAÑOL necesitás una API Key gratuita "
            "de TMDb (The Movie Database). Es instantánea y gratis para uso "
            "personal — elegí \"Developer\" al anotarte.",
        )
        if not api_key:
            return

        displayed_title = self.detail_view.title_label.text()
        folder_url = self._detail_folder_url or ""
        search_title = self._search_title_for_detail(folder_url, displayed_title)
        # si el título tiene un año entre paréntesis, ej. "Interestelar (2014)",
        # lo separamos para que la búsqueda en TMDb sea más precisa
        match = re.search(r"\((\d{4})\)\s*$", search_title)
        year = match.group(1) if match else None
        clean_title = re.sub(r"\s*\(\d{4}\)\s*$", "", search_title).strip()

        tipo = "serie" if self._detail_media_type == "tv" else "película"
        self.detail_view.set_synopsis(f"Buscando \"{clean_title}\" ({tipo}) en TMDb (en español)…")
        self._imdb_request_id += 1
        self._imdb_manual_request = True
        try:
            self._io_executor.submit(
                self._fetch_imdb_bg, api_key, clean_title, year,
                self._detail_media_type, self._imdb_request_id, folder_url,
            )
        except RuntimeError:
            pass

    def _on_edit_title_requested(self):
        """El usuario corrige a mano el nombre con el que se busca la ficha:
        útil cuando la carpeta del servidor tiene el título mal escrito y
        TMDb no encuentra nada ("The mandalorian X1")."""
        folder_url = self._detail_folder_url or ""
        if not folder_url:
            return

        # Guardamos la corrección sobre la RAÍZ de la serie (si es una
        # carpeta de temporada), así vale para todas las temporadas.
        key = self._series_root_url(folder_url)
        # Pre-cargamos con lo que ya había: el override guardado, o el
        # nombre que se usaría igual (título mostrado / carpeta padre).
        current = (
            self.title_overrides.get(key)
            or self._search_title_for_detail(
                folder_url, self.detail_view.title_label.text()
            )
        )
        is_series = self._detail_media_type == "tv"
        dlg = SearchTitleDialog(current, is_series, self)
        if dlg.exec() != SearchTitleDialog.Accepted or not dlg.title:
            return

        self.title_overrides.set(key, dlg.title)
        # La ficha cacheada (si la había) es de la búsqueda vieja y ya no
        # vale: la borramos para que no pise el resultado nuevo. Como el
        # caché es un JSON en disco, lo reescribimos sin esa clave.
        self.meta_store.remove(folder_url)
        if key != folder_url:
            self.meta_store.remove(key)

        # Refrescamos el título visible con lo que escribió el usuario
        # (sin el año entre paréntesis, que solo sirve para la búsqueda).
        shown = re.sub(r"\s*\(\d{4}\)\s*$", "", dlg.title).strip() or dlg.title
        self.detail_view.set_title(shown)

        # Y disparamos la búsqueda ya, sin obligar a tocar otro botón.
        self._on_imdb_requested()

    def _fetch_imdb_bg(self, api_key: str, title: str, year: str | None,
                       media_type: str, request_id: int, folder_url: str):
        info, error = tmdb.fetch_media_info(api_key, title, year, language="es-ES", media_type=media_type)
        self._imdb_ready_signal.emit(info if not error else None, error, folder_url, request_id)

    def _on_imdb_ready(self, info: dict | None, error: str, folder_url: str, request_id: int = -1):
        if request_id != -1 and request_id != self._imdb_request_id:
            return
        if error:
            if self.stack.currentWidget() is self.detail_view and folder_url == self._detail_folder_url:
                self.detail_view.set_synopsis(f"TMDb: {error}")
                # Si el usuario buscó a mano y no apareció nada, lo más
                # probable es que el nombre de la carpeta esté mal
                # escrito: le ofrecemos corregirlo en el momento.
                if self._imdb_manual_request and self._is_not_found_error(error):
                    self._offer_title_correction(folder_url, error)
            return
        if info:
            # _on_meta_ready guarda en caché, actualiza el home y aplica
            # a la vista de detalle si sigue abierta esta carpeta
            self._meta_ready_signal.emit(folder_url, meta_from_tmdb_info(info))

    @staticmethod
    def _is_not_found_error(error: str) -> bool:
        return "no se encontró" in (error or "").lower()

    def _offer_title_correction(self, folder_url: str, error: str):
        """Pregunta si quiere corregir el nombre y, si acepta, abre el
        diálogo de corrección (mismo camino que el botón «Corregir nombre»)."""
        box = QMessageBox(self)
        box.setWindowTitle("No se encontró en TMDb")
        box.setIcon(QMessageBox.Question)
        box.setText(
            "TMDb no encontró esta ficha.\n\n"
            "Puede que el nombre de la carpeta esté mal escrito. "
            "¿Querés corregirlo y volver a buscar?"
        )
        box.setInformativeText(error)
        yes = box.addButton("✏  Corregir nombre", QMessageBox.AcceptRole)
        box.addButton("Cancelar", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is yes:
            self._on_edit_title_requested()

    def _on_online_subtitles_requested(self):
        api_key = self._ensure_api_key(
            "opensubtitles_api_key", "OpenSubtitles",
            "https://www.opensubtitles.com/en/consumers",
            "Para buscar subtítulos online necesitás una API Key gratuita "
            "de OpenSubtitles. Registrate como \"Consumer\" en su sitio — "
            "es gratis e instantáneo (la cuenta gratis tiene una cuota "
            "chica de descargas por día).",
        )
        if not api_key:
            return

        default_query = re.sub(r"\.[A-Za-z0-9]+$", "", self.player.current_title() or "")
        default_query = re.sub(r"[._]", " ", default_query).strip()
        dlg = SubtitleSearchDialog(api_key, default_query, self)
        dlg.subtitle_chosen.connect(self.player.add_local_subtitle)
        dlg.exec()

    # ------------------------------------------------------------------
    # Historial ("continuar viendo") — pantalla inicial de la app
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Búsqueda global (todo el servidor, no solo la carpeta actual)
    # ------------------------------------------------------------------
    def _on_global_search_requested(self):
        query = self.search_box.text().strip()

        if self._active_search_dialog is not None:
            # ya hay uno abierto: solo lo traemos al frente y actualizamos
            self._active_search_dialog.raise_()
            self._active_search_dialog.activateWindow()
            return

        dlg = GlobalSearchDialog(initial_query=query, parent=self)
        dlg.item_chosen.connect(self._on_search_result_chosen)
        dlg.search_requested.connect(self._on_search_query)
        dlg.reindex_requested.connect(self._refresh_sitemap_for_search)
        self._active_search_dialog = dlg

        if self.sitemap.paths:
            dlg.set_index_ready(len(self.sitemap.paths))
        else:
            dlg.set_status("⏳ Preparando el índice desde listado.html…")
            self._load_sitemap_for_search()

        dlg.exec()
        self._active_search_dialog = None

    def _load_sitemap_for_search(self):
        if self._sitemap_loading:
            return
        self._sitemap_loading = True
        try:
            self._io_executor.submit(self._load_sitemap_bg)
        except RuntimeError:
            self._sitemap_loading = False

    def _load_sitemap_bg(self):
        try:
            self.sitemap.ensure_loaded()
        finally:
            self._sitemap_ready_signal.emit()

    def _refresh_sitemap_for_search(self):
        if self._sitemap_loading:
            return
        self._sitemap_loading = True
        dlg = self._active_search_dialog
        if dlg is not None:
            dlg.set_status("⏳ Actualizando el árbol de carpetas…")
        try:
            self._io_executor.submit(self._refresh_sitemap_bg)
        except RuntimeError:
            self._sitemap_loading = False

    def _refresh_sitemap_bg(self):
        try:
            self.sitemap.fetch()
        finally:
            self._sitemap_ready_signal.emit()

    def _on_sitemap_ready(self):
        self._sitemap_loading = False
        dlg = self._active_search_dialog
        if dlg is None:
            return
        try:
            dlg.set_index_ready(len(self.sitemap.paths))
            if dlg.query_input.text().strip():
                self._on_search_query(dlg.query_input.text())
        except RuntimeError:
            pass

    def _on_search_query(self, query: str):
        dlg = self._active_search_dialog
        if dlg is None:
            return
        if not query.strip():
            dlg.show_results([], "")
            return
        if not self.sitemap.paths:
            dlg.set_status("⏳ Preparando el índice desde listado.html…")
            self._load_sitemap_for_search()
            return
        results = self.sitemap.search(query)
        label = f"{len(results)} resultado(s) en el árbol del servidor"
        try:
            dlg.show_results(results, label)
        except RuntimeError:
            pass

    def _on_search_result_chosen(self, url: str, is_dir: bool):
        target = url if is_dir else url.rsplit("/", 1)[0] + "/"
        self.navigate_to(target, push_history=True)

    def _show_history(self):
        items = self.progress.list_in_progress()
        self.history_view.load(items)
        self.stack.setCurrentWidget(self.history_view)
        self.close_player_btn.hide()
        self.current_url = None
        self.breadcrumb.setText("Historial")

        for item in items:
            try:
                self._io_executor.submit(self._fetch_history_cover_bg, item["url"])
            except RuntimeError:
                pass

    def _fetch_history_cover_bg(self, video_url: str, suffix: str = "#historycover"):
        folder_url = video_url.rsplit("/", 1)[0] + "/"
        listing = self.client.list_dir(folder_url)  # cacheado, no siempre pega a la red
        if listing.error:
            return
        candidates = in_folder_poster_candidates(listing.entries)
        if candidates:
            self.thumbnails.request(video_url + suffix, candidates)

    def _on_history_play_requested(self, video_url: str, title: str, position: float):
        # No hacer red acá: esto corre en el hilo de la GUI y un listado
        # lento congelaría toda la ventana. Buscamos los subtítulos en
        # segundo plano y arrancamos la reproducción de inmediato.
        self._open_player(video_url, title, start_at=position, subtitle_urls=[])
        try:
            self._io_executor.submit(self._load_history_subs_bg, video_url)
        except RuntimeError:
            pass

    def _load_history_subs_bg(self, video_url: str):
        folder_url = video_url.rsplit("/", 1)[0] + "/"
        listing = self.client.list_dir(folder_url)
        if listing.error:
            return
        entry = next((e for e in listing.entries if e.url == video_url), None)
        if not entry:
            return
        for i, sub_url in enumerate(subtitle_urls_for(entry, listing.entries)):
            # el player ya puede haberse cerrado o cambiado de video;
            # seleccionamos solo el primero (mismo criterio que antes).
            self._add_subtitle_signal.emit(video_url, sub_url, i == 0)

    def _on_history_subtitle_ready(self, video_url: str, subtitle_url: str, select: bool):
        if self.player.current_url != video_url:
            return  # el usuario ya cambió de video
        self.player.add_subtitle_url(subtitle_url, select=select)

    def _on_history_remove_requested(self, video_url: str):
        self.progress.remove(video_url)
        self.history_view.remove_item(video_url)

    # ------------------------------------------------------------------
    # Home (pantalla inicial estilo plataforma de streaming)
    # ------------------------------------------------------------------
    def _show_home(self):
        self.stack.setCurrentWidget(self.home_view)
        self.close_player_btn.hide()
        self.current_url = None
        self.breadcrumb.setText("Inicio")
        self._update_fav_button()
        # Refresca si nunca se cargó o si los datos son viejos (el
        # contenido del servidor puede haber cambiado).
        if not self._home_built_at or (time.time() - self._home_built_at) > HOME_STALE_SECONDS:
            self._refresh_home()

    def _show_favorites(self):
        """Ir a Inicio y bajar hasta la fila de Favoritos."""
        if not self.favorites:
            self._show_home()
            self.status_label.setText(
                "Todavía no marcaste favoritos: usá la ☆ de arriba a la derecha."
            )
            QTimer.singleShot(5000, lambda: self.status_label.setText(""))
            return
        self._pending_fav_scroll = True
        self._show_home()
        QTimer.singleShot(0, self._scroll_to_favorites)

    def _scroll_to_favorites(self):
        if not self._pending_fav_scroll:
            return
        self.home_view.scroll_to_row("favorites")
        self._pending_fav_scroll = False

    def _refresh_home(self):
        self.home_view.show_loading("Cargando catálogo…")
        self.status_label.setText("Cargando portada…")
        try:
            self._io_executor.submit(self._load_home_bg)
        except RuntimeError:
            pass  # la app se está cerrando

    # Límites del escaneo del home: el árbol real del servidor es
    # profundo (Peliculas/Extranjeras/1900s/1901/Film/) y no queremos
    HOME_CARDS_PER_ROW = 24

    def _collect_playable_folders(self, root_url: str, limit: int) -> list[Entry]:
        """Carpetas \"de contenido\" dentro de una categoría, usando el
        árbol que publica el servidor (`listado.html`) en vez de escanear
        carpeta por carpeta. Cae al escaneo directo si no hay árbol."""
        root_path = urlparse(root_url).path.rstrip("/")
        if self.sitemap.paths:
            folders = self.sitemap.content_folders(root_path, limit=limit)
            if folders:
                return [
                    Entry(name=f.rsplit("/", 1)[-1], url=BASE_URL.rstrip("/") + f + "/",
                          is_dir=True)
                    for f in folders
                ]
        return self._scan_playable_folders(root_url, limit)

    def _scan_playable_folders(self, root_url: str, limit: int) -> list[Entry]:
        """Respaldo sin árbol: BFS acotado buscando carpetas con video."""
        results: list[Entry] = []
        listings = 0
        queue: list[tuple[str, int]] = [(root_url, 0)]
        visited: set[str] = {root_url}
        while queue and listings < 40 and len(results) < limit:
            folder_url, depth = queue.pop(0)
            listing = self.client.list_dir(folder_url)
            listings += 1
            if listing.error:
                continue
            subdirs = [e for e in listing.entries if e.is_dir]
            if any(e.is_video for e in listing.entries) and folder_url != root_url:
                results.append(Entry(
                    name=[p for p in urlparse(folder_url).path.split("/") if p][-1] or folder_url,
                    url=folder_url, is_dir=True,
                ))
                continue
            if depth >= 5:
                continue
            for e in subdirs:
                if e.url not in visited:
                    visited.add(e.url)
                    queue.append((e.url, depth + 1))
        return results

    def _load_home_bg(self):
        """Corre en background: arma las filas del home a partir del
        árbol de carpetas del sitio + progreso + favoritos, y emite la
        estructura completa de una."""
        rows: list[tuple[str, str, list[CardData]]] = []
        series_cards: list[CardData] = []
        movie_cards: list[CardData] = []

        # Descarga/actualiza el árbol del sitio si hace falta (una sola
        # descarga de listado.html; después queda cacheado en disco).
        try:
            self.sitemap.ensure_loaded()
        except Exception:
            pass

        row_titles = {
            "movies": "Películas",
            "series": "Series",
            "kids": "Infantiles",
        }
        folder_keys = {
            "peliculas": "movies", "películas": "movies",
            "series": "series",
            "infantiles": "kids",
        }
        for _label, folder in CATEGORY_SHORTCUTS:
            url = BASE_URL + folder + "/"
            entries = self._collect_playable_folders(url, self.HOME_CARDS_PER_ROW)
            if not entries:
                continue
            cards = [self._card_for_entry(e) for e in entries[: self.HOME_CARDS_PER_ROW]]
            if not cards:
                continue
            key = folder_keys.get(folder.lower(), folder.lower())
            rows.append((key, row_titles.get(key, folder), cards))
            if key == "series":
                series_cards = cards
            elif key == "movies":
                movie_cards = cards

        # --- Favoritos: primera fila del home ---
        fav_cards = []
        for fav in self.favorites[:16]:
            fav_cards.append(CardData(
                key=fav["url"], title=_clean_title(fav["name"]), url=fav["url"],
            ))
        if fav_cards:
            rows.insert(0, ("favorites", "Favoritos", fav_cards))

        # --- Continuar viendo (desde el progreso local) ---
        continue_cards = []
        for item in self.progress.list_in_progress():
            title = clean_display_title(item.get("title") or "") or item.get("title") or "(sin título)"
            continue_cards.append(CardData(
                key=item["url"], title=title, url=item["url"], is_video=True,
                meta=f"▶ {int(item['fraction'] * 100)}% visto",
                progress=item["fraction"],
                payload={"position": item["position"]},
            ))
        if continue_cards:
            rows.insert(1 if fav_cards else 0, ("continue", "Continuar viendo", continue_cards))

        # --- Agregados recientemente: el sitio expone una carpeta
        # "Recientes" en la raíz, así que la usamos directamente en vez
        # de inferir fechas (el árbol de carpetas no las trae). ---
        seen_urls = {c.url for _k, _t, cards in rows for c in cards}
        if any(p.startswith("/Recientes/") for p in self.sitemap.paths):
            recent_entries = self._collect_playable_folders(BASE_URL + "Recientes/", 16)
        else:
            recent_entries = []
        recent_cards = [
            self._card_for_entry(e) for e in recent_entries if e.url not in seen_urls
        ]
        if recent_cards:
            rows.append(("recent", "Agregados recientemente", recent_cards))

        # --- Hero: mezcla aleatoria de películas y series recientes.
        # Antes salía casi siempre de Peliculas/Cubanas porque se usaban
        # las mismas tarjetas de las filas (y esas filas se llenaban con
        # la primera subcarpeta grande). Ahora se arma un pool aparte,
        # ponderado por año, y se eligen títulos al azar en cada carga. ---
        hero = self._hero_cards(movie_cards, series_cards, limit=6)
        for card in hero:
            stored = self.meta_store.get(card.url)
            meta_bits = []
            if stored:
                if stored.title:
                    card.title = stored.title
                meta_bits = stored.chips()[:3]
            elif card.meta:
                meta_bits = [card.meta]
            card.meta = "  ·  ".join(meta_bits)
            card.payload = {"synopsis": (stored.overview[:180] + "…") if stored and stored.overview else ""}

        self._home_ready_signal.emit({"rows": rows, "hero": hero})

    def _hero_cards(self, movie_cards: list[CardData], series_cards: list[CardData],
                    limit: int = 6) -> list[CardData]:
        """Elige títulos para el banner: mezcla películas y series,
        priorizando los años más recientes y variando en cada carga."""
        current_year = time.localtime().tm_year
        movie_pool: list[str] = []
        series_pool: list[str] = []
        sitemap = self.sitemap

        if sitemap.paths:
            # Películas extranjeras: carpetas por año (2026, 2025, 2024…).
            ext_root = "/Peliculas/Extranjeras"
            year_dirs = [
                c for c in sitemap.children(ext_root)
                if re.fullmatch(r"(19|20)\d{2}", c.rsplit("/", 1)[-1])
            ]
            year_dirs.sort(key=lambda p: int(p.rsplit("/", 1)[-1]), reverse=True)
            # Más cupo para los años más nuevos: 2026 pesa más que 2023.
            for year_dir, quota in zip(year_dirs[:4], (8, 6, 4, 2)):
                leaves = sitemap.leaf_children(year_dir)
                random.shuffle(leaves)
                movie_pool.extend(leaves[:quota])

            # Cubanas recientes (el nombre suele empezar con el año).
            cubanas = [
                c for c in sitemap.children("/Peliculas/Cubanas")
                if not sitemap.children(c)
            ]
            recent_cubanas = [
                c for c in cubanas
                if int(parse_year(c.rsplit("/", 1)[-1]) or 0) >= current_year - 10
            ]
            random.shuffle(recent_cubanas)
            movie_pool.extend(recent_cubanas[:2])

            # Series: carpetas de primer nivel con año reciente en el nombre.
            for root in ("/Series/Espanol", "/Series/Ingles",
                         "/Series/NETFLIX", "/Series/Cubanos"):
                series_folders = sitemap.children(root)
                dated = [
                    c for c in series_folders
                    if int(parse_year(c.rsplit("/", 1)[-1]) or 0) >= current_year - 3
                ]
                random.shuffle(dated)
                series_pool.extend(dated[:4])

            # Lo que el servidor marcó como reciente (Recientes/).
            for path in sitemap.leaf_children("/Recientes"):
                name = path.rsplit("/", 1)[-1]
                if re.search(r"(?i)(?:^|[.\s_-])s\d{1,2}(?:[.\s_-]|$)|season|temporada|cap[ií]tulo", name):
                    series_pool.append(path)
                else:
                    movie_pool.append(path)

        # Respaldo: si el árbol no trajo nada, usar las tarjetas de fila.
        if not movie_pool:
            movie_pool = [c.url for c in movie_cards]
        if not series_pool:
            series_pool = [c.url for c in series_cards]

        random.shuffle(movie_pool)
        random.shuffle(series_pool)
        chosen: list[str] = []
        turn_movie = True
        while len(chosen) < limit and (movie_pool or series_pool):
            pool = movie_pool if (turn_movie and movie_pool) or not series_pool else series_pool
            turn_movie = not turn_movie
            url = pool.pop()
            if url not in chosen:
                chosen.append(url)

        cards: list[CardData] = []
        for url in chosen:
            name = unquote(urlparse(url).path.rstrip("/").rsplit("/", 1)[-1])
            cards.append(self._card_for_entry(Entry(name=name, url=url, is_dir=True)))
        return cards

    def _card_for_entry(self, entry: Entry) -> CardData:
        """CardData de una entrada del listado, usando el caché de
        metadatos si ya hay ficha de TMDb para esa carpeta."""
        title = clean_display_title(entry.name) or entry.name
        meta = ""
        stored = self.meta_store.get(entry.url)
        if stored:
            if stored.title:
                title = stored.title
            meta = "  ·  ".join(stored.chips()[:2])
        elif parse_year(entry.name):
            meta = parse_year(entry.name) or ""
        return CardData(key=entry.url, title=title, url=entry.url,
                        is_video=entry.is_video, meta=meta)

    @staticmethod
    def _parse_entry_date(date_str: str) -> float:
        """Fecha del listado de Apache ("2024-01-05 12:30" o
        "05-Jan-24 12:30") -> timestamp, o 0 si no se pudo parsear."""
        date_str = (date_str or "").strip()
        for fmt in ("%Y-%m-%d %H:%M", "%d-%b-%Y %H:%M", "%d-%b-%y %H:%M", "%Y-%m-%d"):
            try:
                return time.mktime(time.strptime(date_str, fmt))
            except ValueError:
                continue
        return 0.0

    def _on_home_ready(self, structure: dict):
        self.home_view.set_structure(structure["rows"], structure["hero"])
        self._home_built_at = time.time()
        self.status_label.setText("")
        if self._pending_fav_scroll:
            QTimer.singleShot(0, self._scroll_to_favorites)

        # Pósters de todas las tarjetas (las carpetas resuelven solas con
        # los nombres típicos de Kodi; los videos necesitan listar su
        # carpeta para buscar la imagen hermana).
        requested: set[str] = set()
        for _key, _title, cards in structure["rows"]:
            for card in cards:
                self._request_card_image(card, requested)
        for card in structure["hero"]:
            self._request_card_image(card, requested)
            stored = self.meta_store.get(card.url)
            if stored and stored.backdrop_url:
                self.thumbnails.request(card.url + "#backdrop", [stored.backdrop_url])

        self._start_home_enrichment(structure)

    def _request_card_image(self, card: CardData, requested: set[str]):
        if card.url in requested:
            return
        requested.add(card.url)
        if card.is_video:
            try:
                self._io_executor.submit(self._fetch_card_cover_bg, card.url)
            except RuntimeError:
                pass
            return
        entry = Entry(name=unquote(card.url.rstrip("/").rsplit("/", 1)[-1]),
                      url=card.url, is_dir=True)
        self.thumbnails.request(card.url + "#card", candidate_urls_for(entry, []))

    def _fetch_card_cover_bg(self, video_url: str):
        """Póster de un video suelto (ej. fila 'Continuar viendo'):
        busca imágenes hermanas en su carpeta."""
        folder_url = video_url.rsplit("/", 1)[0] + "/"
        listing = self.client.list_dir(folder_url)
        if listing.error:
            return
        entry = next((e for e in listing.entries if e.url == video_url), None)
        candidates = candidate_urls_for(entry, listing.entries) if entry else []
        if not candidates:
            candidates = in_folder_poster_candidates(listing.entries)
        if candidates:
            self.thumbnails.request(video_url + "#card", candidates)

    def _on_home_play(self, card: CardData):
        """Reproducción pedida desde una tarjeta del home."""
        if not card.is_video:
            # es una carpeta (película/serie): la ruta natural es la vista
            # de detalle, donde está el botón de reproducir grande
            self.navigate_to(card.url, push_history=True)
            return
        position = 0.0
        if isinstance(card.payload, dict):
            position = float(card.payload.get("position") or 0)
        if position > 0:
            self._open_player(card.url, card.title, start_at=position, subtitle_urls=[])
            try:
                self._io_executor.submit(self._load_history_subs_bg, card.url)
            except RuntimeError:
                pass
        else:
            self._open_player_with_resume(card.url, card.title, subtitle_urls=[])

    # --- Enriquecimiento de metadatos vía TMDb (opcional) ---------------
    def _start_home_enrichment(self, structure: dict):
        """Si hay API key de TMDb configurada, busca la ficha completa de
        las carpetas que todavía no están en el caché (en background, con
        cortesía ante el rate limit). Los resultados se aplican solos a
        medida que llegan vía _meta_ready_signal."""
        api_key = self.config.get("tmdb_api_key")
        if not api_key:
            return
        targets: list[CardData] = []
        seen: set[str] = set()
        pool = list(structure["hero"]) + [c for _k, _t, cards in structure["rows"] for c in cards]
        for card in pool:
            if card.is_video or card.url in seen or self.meta_store.has(card.url):
                continue
            seen.add(card.url)
            targets.append(card)
        if not targets:
            return
        try:
            self._io_executor.submit(self._enrich_home_bg, api_key,
                                     [(c.url, c.title) for c in targets[:40]])
        except RuntimeError:
            pass

    def _enrich_home_bg(self, api_key: str, targets: list[tuple[str, str]]):
        for url, title in targets:
            path_lower = urlparse(url).path.lower()
            name_lower = path_lower.rstrip("/").rsplit("/", 1)[-1]
            # Series fuera de /Series (p. ej. carpetas en Recientes con
            # "S02" o "Temporada"): que TMDb busque como serie, no como
            # película — antes esas fichas no encontraban nada.
            is_series = "/series" in path_lower or bool(re.search(
                r"(?:^|[.\s_-])s\d{1,2}(?:$|[.\s_-])|season|temporada",
                name_lower,
            ))
            media_type = "tv" if is_series else "movie"
            year = parse_year(title)
            clean = re.sub(r"\s*\(\d{4}\)\s*$", "", title).strip()
            info, _error = tmdb.fetch_media_info(
                api_key, clean, year, language="es-ES", media_type=media_type,
            )
            if info:
                self._meta_ready_signal.emit(url, meta_from_tmdb_info(info))
            time.sleep(0.3)  # cortesía con el rate limit de TMDb

    def _on_meta_ready(self, folder_url: str, meta: MediaMeta):
        """Ficha de TMDb llegada (del enriquecimiento del home o del
        detalle): guarda en el caché y aplica a lo que esté visible."""
        self.meta_store.put(folder_url, meta)
        self.home_view.update_card_meta(
            folder_url,
            title=meta.title or None,
            meta="  ·  ".join(meta.chips()[:2]),
        )
        if meta.backdrop_url:
            self.thumbnails.request(folder_url + "#backdrop", [meta.backdrop_url])
        if (self.stack.currentWidget() is self.detail_view
                and self._detail_folder_url == folder_url):
            self._apply_meta_to_detail(meta)

    def _apply_meta_to_detail(self, meta: MediaMeta):
        # Si TMDb devolvió un título, mostramos ESE (bien escrito) en vez
        # del nombre crudo de la carpeta — es justo lo que se busca al
        # corregir un nombre mal escrito.
        if meta.title:
            self.detail_view.set_title(meta.title)
        self.detail_view.set_chips(meta.chips())
        if meta.overview:
            self.detail_view.set_synopsis(meta.overview)
        if meta.poster_url and self._detail_poster_key:
            self.thumbnails.request(self._detail_poster_key + "#tmdb", [meta.poster_url])

    # ------------------------------------------------------------------
    # Listado: modo lista / modo grilla con carátulas
    # ------------------------------------------------------------------
    def _toggle_view_mode(self):
        self.view_mode = "grid" if self.view_toggle_btn.isChecked() else "list"
        self.view_toggle_btn.setText(
            "☰ Vista lista" if self.view_mode == "grid" else "🖼 Vista grilla"
        )
        self._apply_view_mode()
        self._populate_list(self.current_entries)

    def _apply_view_mode(self):
        if self.view_mode == "grid":
            self.file_list.setViewMode(QListWidget.IconMode)
            self.file_list.setIconSize(GRID_ICON_SIZE)
            self.file_list.setGridSize(GRID_CELL_SIZE)
            self.file_list.setResizeMode(QListWidget.Adjust)
            self.file_list.setMovement(QListWidget.Static)
            self.file_list.setWordWrap(True)
            self.file_list.setSpacing(8)
        else:
            self.file_list.setViewMode(QListWidget.ListMode)
            self.file_list.setIconSize(QSize(0, 0))
            self.file_list.setGridSize(QSize())
            self.file_list.setSpacing(2)

    def _populate_list(self, entries: list[Entry]):
        self.file_list.clear()
        self._grid_items.clear()

        if self.view_mode == "grid":
            self._apply_view_mode()
            for entry in entries:
                item = QListWidgetItem(self._grid_caption(entry))
                item.setIcon(QIcon(_make_placeholder(entry)))
                item.setData(Qt.UserRole, entry)
                item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
                self.file_list.addItem(item)
                self._grid_items[entry.url] = item

                candidates = candidate_urls_for(entry, entries)
                self.thumbnails.request(entry.url, candidates)
            return

        for entry in entries:
            icon = FOLDER_ICON if entry.is_dir else (VIDEO_ICON if entry.is_video else FILE_ICON)
            extra = f"   {entry.size}" if entry.size else ""
            progress_tag = self._progress_tag(entry)
            item = QListWidgetItem(f"{icon}  {entry.name}{extra}{progress_tag}")
            item.setData(Qt.UserRole, entry)
            self.file_list.addItem(item)

    def _grid_caption(self, entry: Entry) -> str:
        name = clean_display_title(entry.name) or entry.name
        if len(name) > 26:
            name = name[:24] + "…"
        return f"{name}{self._progress_tag(entry)}"

    def _progress_tag(self, entry: Entry) -> str:
        if not entry.is_video:
            return ""
        frac = self.progress.fraction(entry.url)
        if frac is None:
            return ""
        return "   ✓ visto" if frac >= 0.95 else f"   ▶ {int(frac * 100)}%"

    def _on_thumbnail_ready(self, key: str, data: bytes):
        # Segunda barrera de seguridad: aunque thumbnails.py ya valida
        # los bytes reales antes de emitir esta señal, no está de más
        # confirmarlo de nuevo acá — pasarle datos que no son una imagen
        # real a QPixmap puede crashear feo en macOS.
        if not _looks_like_real_image(data):
            return

        # ¿Es la carátula de la vista de detalle actual? (incluye el
        # póster alternativo que puede venir de TMDb)
        if self._detail_poster_key and key in (
            self._detail_poster_key,
            self._detail_poster_key + "#imdb",
            self._detail_poster_key + "#tmdb",
        ):
            pix = QPixmap()
            if pix.loadFromData(data):
                scaled = pix.scaled(
                    self.detail_view.POSTER_SIZE[0], self.detail_view.POSTER_SIZE[1],
                    Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
                )
                self.detail_view.set_poster_pixmap(scaled)
            return

        # ¿Es un póster de tarjeta del home?
        if key.endswith("#card"):
            pix = QPixmap()
            if pix.loadFromData(data):
                scaled = pix.scaled(
                    CARD_POSTER_SIZE[0], CARD_POSTER_SIZE[1],
                    Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
                )
                self.home_view.set_poster(key[: -len("#card")], scaled)
            return

        # ¿Es un backdrop panorámico (hero del home o vista de detalle)?
        if key.endswith("#backdrop"):
            base = key[: -len("#backdrop")]
            pix = QPixmap()
            if pix.loadFromData(data):
                scaled = pix.scaled(
                    BACKDROP_SIZE, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
                )
                if (self.stack.currentWidget() is self.detail_view
                        and base == self._detail_folder_url):
                    self.detail_view.set_backdrop_pixmap(scaled)
                else:
                    self.home_view.set_backdrop(base, scaled)
            return

        # ¿Es la carátula de un ítem del Historial?
        if key.endswith("#historycover"):
            pix = QPixmap()
            if pix.loadFromData(data):
                scaled = pix.scaled(
                    HISTORY_COVER_SIZE[0], HISTORY_COVER_SIZE[1],
                    Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
                )
                self.history_view.set_cover(key[: -len("#historycover")], scaled)
            return

        # ¿Es la carátula de la carpeta de música abierta?
        if key.endswith("#musiccover"):
            if self.stack.currentWidget() is self.music_view:
                pix = QPixmap()
                if pix.loadFromData(data):
                    scaled = pix.scaled(
                        ALBUM_COVER_SIZE[0], ALBUM_COVER_SIZE[1],
                        Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation,
                    )
                    self.music_view.set_cover_pixmap(scaled)
                    self._music_cover_set = True
            return

        item = self._grid_items.get(key)
        if not item:
            return  # el usuario navegó a otra carpeta antes de que llegara
        pix = QPixmap()
        if pix.loadFromData(data):
            scaled = pix.scaled(
                GRID_ICON_SIZE, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            item.setIcon(QIcon(scaled))

    def _apply_filter(self, text: str):
        text = text.lower().strip()
        filtered = [e for e in self.current_entries if text in e.name.lower()] if text else self.current_entries
        self._populate_list(filtered)

    def _on_item_activated(self, item: QListWidgetItem):
        entry: Entry | None = item.data(Qt.UserRole)
        if entry is None:
            # Ítem especial de "reintentar" tras un error de carga
            retry_url = getattr(self, "_pending_retry_url", None)
            if retry_url:
                self.navigate_to(retry_url, push_history=False, force=True)
            return
        if entry.is_dir:
            self.navigate_to(entry.url, push_history=True)
        elif entry.is_video:
            self._play_video_with_sub_popup(entry, self.current_entries)
        else:
            QMessageBox.information(
                self, "Archivo no reproducible",
                f"'{entry.name}' no parece un video soportado.\n\n"
                "Podés descargarlo con clic derecho › Descargar.",
            )

    def go_back(self):
        if self.history_pos > 0:
            self.history_pos -= 1
            self.navigate_to(self.history[self.history_pos], push_history=False)

    def go_forward(self):
        if self.history_pos < len(self.history) - 1:
            self.history_pos += 1
            self.navigate_to(self.history[self.history_pos], push_history=False)

    def refresh_current(self):
        if self.current_url:
            self.navigate_to(self.current_url, push_history=False, force=True)

    def _update_breadcrumb(self, url: str):
        path = urlparse(url).path
        parts = [_clean_title(p) for p in path.split("/") if p]
        crumb = "Inicio" + ("".join(f"  ›  {p}" for p in parts))
        self.breadcrumb.setText(crumb)

    # ------------------------------------------------------------------
    # Menú contextual (clic derecho) sobre archivos/carpetas
    # ------------------------------------------------------------------
    def _show_file_menu(self, pos):
        item = self.file_list.itemAt(pos)
        if not item:
            return
        entry: Entry | None = item.data(Qt.UserRole)
        menu = QMenu(self)

        if entry is None:
            return  # ítem especial de "reintentar": no tiene acciones de archivo

        if entry.is_dir:
            menu.addAction("Abrir carpeta", lambda: self.navigate_to(entry.url, push_history=True))
            menu.addAction("⬇ Descargar toda esta carpeta", lambda: self._download_folder_requested(entry))
        elif entry.is_video:
            menu.addAction(
                "▶ Reproducir",
                lambda: self._play_video_with_sub_popup(entry, self.current_entries),
            )
            menu.addAction("⬇ Descargar", lambda: self._start_download(entry))
            if self.progress.fraction(entry.url) is not None:
                menu.addAction("Olvidar progreso", lambda: self._forget_progress(entry.url))
        else:
            menu.addAction("⬇ Descargar", lambda: self._start_download(entry))

        menu.exec(self.file_list.viewport().mapToGlobal(pos))

    def _forget_progress(self, url: str):
        self.progress.remove(url)
        self._populate_list(self.current_entries)

    # ------------------------------------------------------------------
    # Reproducción
    # ------------------------------------------------------------------
    def _open_player_with_resume(self, url: str, title: str, subtitle_urls: list | None = None):
        resume_at = self.progress.resumable_position(url)
        start_at = 0.0

        if resume_at:
            box = QMessageBox(self)
            box.setWindowTitle("Continuar viendo")
            box.setText(
                f"Quedaste en {_fmt_time(resume_at)} de '{title}'.\n"
                "¿Querés continuar desde ahí o empezar de nuevo?"
            )
            continue_btn = box.addButton("Continuar", QMessageBox.AcceptRole)
            box.addButton("Empezar de nuevo", QMessageBox.RejectRole)
            box.setDefaultButton(continue_btn)
            box.exec()
            if box.clickedButton() is continue_btn:
                start_at = resume_at
            else:
                self.progress.remove(url)

        self._open_player(url, title, start_at=start_at, subtitle_urls=subtitle_urls)

    def _open_player(self, url: str, title: str, start_at: float = 0.0, subtitle_urls: list | None = None):
        self.stack.setCurrentWidget(self.player)
        self.close_player_btn.show()
        self.player.play(url, title=title, start_at=start_at, subtitle_urls=subtitle_urls)

    def _on_video_finished(self):
        """Al llegar al final de un video, si hay otro video después en
        la misma carpeta (orden alfabético del listado), lo reproduce
        automáticamente — pensado para series (episodio 1 → 2 → 3…)."""
        current_url = self.player.current_url
        if not current_url or not self.current_entries:
            return
        video_entries = [e for e in self.current_entries if e.is_video]
        urls = [e.url for e in video_entries]
        if current_url not in urls:
            return
        idx = urls.index(current_url)
        if idx + 1 >= len(video_entries):
            return  # era el último video de la carpeta, no hay más
        next_entry = video_entries[idx + 1]
        subs = subtitle_urls_for(next_entry, self.current_entries)
        self._open_player(next_entry.url, next_entry.name, subtitle_urls=subs)

    def _close_player(self):
        self._save_current_progress()
        self.player.stop()
        # Si el video se abrió desde el home (sin navegar a su carpeta),
        # volvemos al home en vez de un listado ajeno.
        if self.current_url is None:
            self.stack.setCurrentWidget(self.home_view)
            self._show_home()
        else:
            self.stack.setCurrentWidget(self.file_list)
        self.close_player_btn.hide()
        # refresca los porcentajes en la lista al volver
        self._populate_list(self.current_entries)

    def _save_current_progress(self):
        url = getattr(self.player, "current_url", None)
        if not url:
            return
        pos, dur = self.player.current_progress()
        if pos and dur:
            self.progress.set(url, pos, dur, title=self.player._current_title)

    def _show_error(self, message: str):
        QMessageBox.warning(self, "Reproductor", message)

    # ------------------------------------------------------------------
    # Descargas
    # ------------------------------------------------------------------
    def _start_download(self, entry: Entry, relative_dir: str = ""):
        task_id = self.downloads.enqueue(entry.url, entry.name, relative_dir=relative_dir)
        label = f"{relative_dir}/{entry.name}" if relative_dir else entry.name
        self._download_labels[task_id] = f"⬇ {label}  —  en cola"
        self._update_downloads_badge()

    def _update_downloads_badge(self):
        active = sum(
            1 for t in self._download_labels
            if (self.downloads.tasks.get(t) and
                self.downloads.tasks[t].status in ("queued", "downloading"))
        )
        self.downloads_btn.setText(f"⬇ {active}" if active else "⬇")

    def _on_download_progress(self, task_id: str, done: int, total: int):
        if task_id not in self._download_labels:
            return
        task = self.downloads.tasks.get(task_id)
        name = task.filename if task else "archivo"
        if total:
            pct = int(done / total * 100)
            mb_done, mb_total = done / 1_048_576, total / 1_048_576
            self._download_labels[task_id] = f"⬇ {name}  —  {pct}%  ({mb_done:.0f} / {mb_total:.0f} MB)"
        else:
            self._download_labels[task_id] = f"⬇ {name}  —  {done / 1_048_576:.0f} MB"

    def _on_download_status(self, task_id: str, status: str):
        task = self.downloads.tasks.get(task_id)
        name = task.filename if task else "archivo"
        if status == "queued":
            self._download_labels[task_id] = f"⬇ {name}  —  en cola"
        elif status == "downloading":
            self._download_labels[task_id] = f"⬇ {name}  —  descargando…"
        elif status == "completed":
            self._download_labels[task_id] = f"✅ {name}  —  completado"
        elif status == "canceled":
            self._download_labels[task_id] = f"⛔ {name}  —  cancelado"
        elif status.startswith("error"):
            self._download_labels[task_id] = f"⚠️ {name}  —  error al descargar"
        self._update_downloads_badge()

    def _rebuild_downloads_menu(self):
        self.dl_menu.clear()
        self.dl_menu.addAction("📂  Abrir carpeta de descargas", self._open_downloads_folder)
        self.dl_menu.addSeparator()
        if not self._download_labels:
            act = self.dl_menu.addAction("(sin descargas)")
            act.setEnabled(False)
            return
        for task_id, label in list(self._download_labels.items()):
            task = self.downloads.tasks.get(task_id)
            if not task:
                continue
            sub = self.dl_menu.addMenu(label)
            if task.status in ("queued", "downloading"):
                sub.addAction("Cancelar", lambda t=task_id: self.downloads.cancel(t))
            if task.status == "completed":
                sub.addAction("Mostrar en Finder", lambda p=task.dest_path: self._reveal_in_finder(p))
        self.dl_menu.addSeparator()
        self.dl_menu.addAction("🧹  Limpiar completadas", self._clear_finished_downloads)

    def _clear_finished_downloads(self):
        for task_id in list(self._download_labels):
            task = self.downloads.tasks.get(task_id)
            if task and task.status in ("completed", "canceled") or (task and task.status.startswith("error")):
                self._download_labels.pop(task_id, None)
        self._update_downloads_badge()

    # ------------------------------------------------------------------
    # Descargar una carpeta completa (recursivo, con subcarpetas)
    # ------------------------------------------------------------------
    def _download_folder_requested(self, entry: Entry):
        self.status_label.setText(f"Escaneando \"{entry.name}\"…")
        try:
            self._io_executor.submit(self._scan_folder_bg, entry.url, entry.name)
        except RuntimeError:
            pass

    def _scan_folder_bg(self, folder_url: str, root_name: str):
        files = []  # (url, filename, relative_dir)
        total_bytes = 0.0
        self._walk_folder_for_download(folder_url, root_name, files, depth=0)
        for _url, _filename, _relative_dir, size_str in files:
            total_bytes += _parse_size_to_bytes(size_str)
        # descartamos el tamaño del tuple para la señal (solo lo usamos acá)
        plain_files = [(u, f, r) for u, f, r, _s in files]
        self._folder_scan_ready_signal.emit(plain_files, root_name, total_bytes)

    def _walk_folder_for_download(self, folder_url: str, relative_dir: str, out: list, depth: int):
        if depth > 10 or len(out) >= 5000:  # topes de seguridad
            return
        listing = self.client.list_dir(folder_url, force=False)
        if listing.error:
            return
        for e in listing.entries:
            if e.is_dir:
                self._walk_folder_for_download(e.url, f"{relative_dir}/{e.name}", out, depth + 1)
            else:
                out.append((e.url, e.name, relative_dir, e.size))

    def _on_folder_scan_ready(self, files: list, root_name: str, total_bytes: float):
        if not files:
            self.status_label.setText(f"\"{root_name}\" no tiene archivos para descargar.")
            return

        size_label = _fmt_bytes(total_bytes) if total_bytes else "tamaño desconocido"
        box = QMessageBox(self)
        box.setWindowTitle("Descargar carpeta completa")
        box.setText(
            f"Se encontraron {len(files)} archivo(s) dentro de \"{root_name}\" "
            f"(~{size_label} en total, estimado).\n\n"
            f"Se van a guardar en:\n~/Downloads/VisualesUCLV/{root_name}/...\n\n"
            "¿Descargar todo?"
        )
        yes_btn = box.addButton("Descargar todo", QMessageBox.AcceptRole)
        box.addButton("Cancelar", QMessageBox.RejectRole)
        box.setDefaultButton(yes_btn)
        box.exec()
        if box.clickedButton() is not yes_btn:
            self.status_label.setText("Descarga de carpeta cancelada.")
            return

        self.status_label.setText(f"Encolando {len(files)} archivo(s) de \"{root_name}\"…")
        for url, filename, relative_dir in files:
            fake_entry = Entry(name=filename, url=url, is_dir=False)
            self._start_download(fake_entry, relative_dir=relative_dir)

    def _reveal_in_finder(self, path: Path):
        import subprocess
        subprocess.run(["open", "-R", str(path)])

    def _open_downloads_folder(self):
        import subprocess
        DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(DOWNLOADS_DIR)])

    # ------------------------------------------------------------------
    # Favoritos
    # ------------------------------------------------------------------
    def _load_favorites(self) -> list[dict]:
        if FAVORITES_FILE.exists():
            try:
                return json.loads(FAVORITES_FILE.read_text())
            except Exception:
                return []
        return []

    def _save_favorites(self):
        FAVORITES_FILE.write_text(json.dumps(self.favorites, ensure_ascii=False, indent=2))

    def _rebuild_fav_menu(self):
        self.fav_menu.clear()
        if not self.favorites:
            act = self.fav_menu.addAction("(sin favoritos todavía)")
            act.setEnabled(False)
        else:
            for fav in self.favorites:
                # unquote acá también, por si el favorito se guardó con el
                # bug viejo (nombre sin decodificar) antes de este arreglo
                label = f"★ {_clean_title(fav['name'])}"
                url = fav["url"]
                self.fav_menu.addAction(label, lambda u=url: self.navigate_to(u, push_history=True))
        self.fav_menu.addSeparator()
        self.fav_menu.addAction(
            "☆ Marcar/desmarcar carpeta actual", self._toggle_current_favorite
        )

    def _toggle_current_favorite(self):
        url = self.current_url
        if not url:
            return
        existing = next((f for f in self.favorites if f["url"] == url), None)
        if existing:
            self.favorites.remove(existing)
        else:
            name = [p for p in urlparse(url).path.split("/") if p]
            label = _clean_title(name[-1]) if name else "Inicio"
            self.favorites.append({"name": label, "url": url})
        self._save_favorites()
        self._update_fav_button()

    def _update_fav_button(self):
        is_fav = any(f["url"] == self.current_url for f in self.favorites)
        self.fav_btn.setText("★" if is_fav else "☆")

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        self._save_current_progress()
        self.player.shutdown()
        self.music_bar.shutdown()
        self.downloads.shutdown()
        self.thumbnails.shutdown()
        self.audio_metadata.shutdown()
        self._io_executor.shutdown(wait=False, cancel_futures=True)
        super().closeEvent(event)
