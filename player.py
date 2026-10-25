"""
player.py
---------
Página de reproducción. Por defecto usa el reproductor **externo** (mpv
como proceso aparte por IPC, ver ``mpv_ipc.py``): abre su propia ventana
como en la versión MVP, con mayor estabilidad.

El modo **embebido** (libmpv dentro de la app, ``mpv_embedded.py``) queda
como opción experimental y solo se usa si se activa explícitamente con
``VISUALES_PLAYER=embedded`` o desde preferencias (``use_embedded_player``).
"""

from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt, QTimer, Signal, QEvent
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSlider, QLabel, QPushButton,
    QStackedWidget, QApplication,
)

from mpv_ipc import MpvIPCPlayer, find_mpv_binary
from mpv_embedded import EmbeddedMpvPlayer, embedded_available
from player_prefs import (
    DEFAULT_SUB_OUTLINE, MAX_SUB_FONT_SIZE, MIN_SUB_FONT_SIZE, SUB_COLORS,
    SUB_FONT_STEP, cache_max_mb, cache_secs, sub_color, sub_font_size,
)

MPV_AVAILABLE = find_mpv_binary() is not None
EMBEDDED_AVAILABLE = embedded_available()


def _fmt_time(seconds: float) -> str:
    if seconds is None or seconds < 0:
        seconds = 0
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


class PlayerWidget(QWidget):
    """Página de reproducción (mpv externo por defecto, embebido opcional)."""

    error_occurred = Signal(str)
    track_finished = Signal()  # el video llegó al final de verdad (no pausa)
    online_subtitles_requested = Signal()
    folder_subtitles_requested = Signal()  # elegir un sub. de la carpeta del video
    _pause_state_signal = Signal(bool)  # puente hilo IPC -> hilo GUI

    IDLE_TEXT_EMBEDDED = (
        "🎬 El video se reproduce dentro de la app.\n"
        "Elegí una película o un episodio para empezar."
    )
    IDLE_TEXT_EXTERNAL = (
        "🎬 El video se abre en una ventana aparte de mpv.\n"
        "Usá estos controles para manejarlo desde acá, o los atajos "
        "normales de mpv (espacio para pausar, flechas para saltar)."
    )

    def __init__(self, config=None, parent=None):
        super().__init__(parent)
        self._config = config
        self._duration = 0.0
        self._seeking = False
        self._mpv = None
        self._current_title = ""
        self.current_url: str | None = None
        self._pending_start_at = 0.0
        self._paused = False
        self._eof_callback_registered = False
        self._seek_callback_registered = False
        self._cinema = False
        self._sub_size = sub_font_size(config)
        self._sub_color = sub_color(config)

        # Vigilante de trabas: si el video deja de avanzar (y mpv no está
        # buffereando ni pausado), intenta destrabarlo solo.
        self._watch_pos: float | None = None
        self._watch_since = time.monotonic()
        self._last_recovery = 0.0
        self._recover_attempts = 0

        # Por defecto usamos mpv externo (como en el MVP) por estabilidad.
        # El embebido solo se activa explícitamente con VISUALES_PLAYER=embedded
        # o con config use_embedded_player=True.
        use_embedded = False
        if config is not None:
            try:
                use_embedded = bool(config.get("use_embedded_player", False))
            except Exception:
                use_embedded = False
        if not use_embedded:
            use_embedded = os.environ.get("VISUALES_PLAYER", "").lower().strip() == "embedded"

        self._embedded = bool(use_embedded and EMBEDDED_AVAILABLE)
        self.video: EmbeddedMpvPlayer | None = None
        if self._embedded:
            try:
                self.video = EmbeddedMpvPlayer(
                    self,
                    cache_secs=cache_secs(config),
                    cache_max_mb=cache_max_mb(config),
                )
                self.video.error_occurred.connect(self.error_occurred)
                self.video.track_finished.connect(self.track_finished)
                self.video.pause_changed.connect(self._on_pause_changed)
                self.video.on_event("end-file", self._on_end_file)
                self.video.on_event("file-loaded", self._on_embedded_file_loaded)
                self._mpv = self.video
            except Exception:
                self._embedded = False
                self.video = None
        self._idle_text = (
            self.IDLE_TEXT_EMBEDDED if self._embedded else self.IDLE_TEXT_EXTERNAL
        )

        self._build_ui()
        self._pause_state_signal.connect(self._on_pause_changed)
        self._install_shortcuts()

        if not (self._embedded or MPV_AVAILABLE):
            self.info_label.setText(
                "No se encontró mpv. Instalalo con:\n"
                "brew install mpv\n"
                "y reiniciá la app."
            )
            self._set_controls_enabled(False)

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # --- Escenario: video embebido o cartel de estado --------------
        self.stage = QStackedWidget()
        self.stage.setObjectName("playerStage")

        self.idle_page = QWidget()
        idle_layout = QVBoxLayout(self.idle_page)
        idle_layout.setContentsMargins(20, 20, 20, 20)
        self.info_label = QLabel(self._idle_text)
        self.info_label.setObjectName("nowPlayingLabel")
        self.info_label.setWordWrap(True)
        self.info_label.setAlignment(Qt.AlignCenter)
        idle_layout.addStretch(1)
        idle_layout.addWidget(self.info_label)
        idle_layout.addStretch(1)
        self.stage.addWidget(self.idle_page)

        if self.video is not None:
            self.stage.addWidget(self.video)
            self.stage.setCurrentWidget(self.video)
        else:
            self.stage.setCurrentWidget(self.idle_page)
        layout.addWidget(self.stage, stretch=1)

        # --- Controles -------------------------------------------------
        controls = QWidget(self)
        controls.setObjectName("playerControls")
        self.controls = controls
        c_layout = QVBoxLayout(controls)
        c_layout.setContentsMargins(14, 10, 14, 10)
        c_layout.setSpacing(4)

        seek_row = QHBoxLayout()
        self.time_label = QLabel("0:00")
        self.time_label.setFixedWidth(48)
        self.seek_slider = QSlider(Qt.Horizontal)
        self.seek_slider.setRange(0, 1000)
        self.seek_slider.sliderPressed.connect(self._on_seek_start)
        self.seek_slider.sliderReleased.connect(self._on_seek_end)
        self.duration_label = QLabel("0:00")
        self.duration_label.setFixedWidth(48)
        seek_row.addWidget(self.time_label)
        seek_row.addWidget(self.seek_slider, stretch=1)
        seek_row.addWidget(self.duration_label)
        c_layout.addLayout(seek_row)

        btn_row = QHBoxLayout()
        self.play_btn = QPushButton("⏸")
        self.play_btn.setFixedWidth(40)
        self.play_btn.clicked.connect(self.toggle_pause)

        self.stop_btn = QPushButton("⏹")
        self.stop_btn.setFixedWidth(40)
        self.stop_btn.clicked.connect(self.stop)

        self.back10_btn = QPushButton("«10s")
        self.back10_btn.clicked.connect(lambda: self.seek_relative(-10))
        self.fwd10_btn = QPushButton("10s»")
        self.fwd10_btn.clicked.connect(lambda: self.seek_relative(10))

        self.sub_btn = QPushButton("CC")
        self.sub_btn.setCheckable(True)
        self.sub_btn.setChecked(True)
        self.sub_btn.setToolTip(
            "Mostrar/ocultar subtítulos\n"
            "Shift+↑ / Shift+↓ (o + / −): tamaño\n"
            "C: cambiar color"
        )
        self.sub_btn.clicked.connect(self._toggle_subs)

        self.online_subs_btn = QPushButton("🌐 Subtítulos")
        self.online_subs_btn.setToolTip("Buscar subtítulos online (OpenSubtitles)")
        self.online_subs_btn.clicked.connect(self.online_subtitles_requested.emit)

        self.folder_subs_btn = QPushButton("📁 Subtítulos de la carpeta")
        self.folder_subs_btn.setToolTip(
            "Elegir un archivo de subtítulo de la misma carpeta del video "
            "(cuando los nombres no coinciden y no se carga solo)"
        )
        self.folder_subs_btn.clicked.connect(self.folder_subtitles_requested.emit)

        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.valueChanged.connect(self._on_volume_changed)

        self.fullscreen_btn = QPushButton("⛶ Pantalla completa")
        self.fullscreen_btn.clicked.connect(self._toggle_fullscreen)

        for w in (self.play_btn, self.stop_btn, self.back10_btn, self.fwd10_btn,
                  self.sub_btn, self.folder_subs_btn, self.online_subs_btn):
            btn_row.addWidget(w)
        btn_row.addStretch(1)
        btn_row.addWidget(QLabel("🔊"))
        btn_row.addWidget(self.volume_slider)
        btn_row.addWidget(self.fullscreen_btn)
        c_layout.addLayout(btn_row)

        layout.addWidget(controls)

        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(400)
        self._ui_timer.timeout.connect(self._refresh_ui)
        self._ui_timer.start()

        # Modo cine (pantalla completa): si pasan unos segundos sin que
        # se mueva el mouse, los controles se esconden solos; cualquier
        # movimiento por la app los trae de vuelta (ver set_cinema_mode).
        self._cinema_hide_timer = QTimer(self)
        self._cinema_hide_timer.setSingleShot(True)
        self._cinema_hide_timer.setInterval(3000)
        self._cinema_hide_timer.timeout.connect(self._hide_controls_cinema)
        # Con el mouse tracking activado en todo el reproductor, los
        # movimientos que no caen sobre el propio PlayerWidget (el video,
        # los botones…) igual llegan y cuentan para no esconder los
        # controles mientras se los está usando.
        self.setMouseTracking(True)
        for hijo in self.findChildren(QWidget):
            hijo.setMouseTracking(True)

    def _install_shortcuts(self):
        def shortcut(key, handler):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(handler)
            return sc

        self._sc_space = shortcut(Qt.Key_Space, self.toggle_pause)
        self._sc_left = shortcut(Qt.Key_Left, lambda: self.seek_relative(-10))
        self._sc_right = shortcut(Qt.Key_Right, lambda: self.seek_relative(10))
        self._sc_full = shortcut(Qt.Key_F, self._toggle_fullscreen)
        self._sc_esc = shortcut(Qt.Key_Escape, self._exit_fullscreen)
        # Subtítulos: agrandar/achicar y cambiar de color sin salir del
        # video. Shift+flechas funciona en cualquier teclado; + y − son
        # el atajo corto.
        self._sc_sub_bigger = shortcut(
            Qt.ShiftModifier | Qt.Key_Up,
            lambda: self.change_sub_size(SUB_FONT_STEP),
        )
        self._sc_sub_smaller = shortcut(
            Qt.ShiftModifier | Qt.Key_Down,
            lambda: self.change_sub_size(-SUB_FONT_STEP),
        )
        self._sc_sub_bigger_plus = shortcut("+", lambda: self.change_sub_size(SUB_FONT_STEP))
        self._sc_sub_smaller_minus = shortcut("-", lambda: self.change_sub_size(-SUB_FONT_STEP))
        self._sc_sub_color = shortcut(Qt.Key_C, self.cycle_sub_color)

    # ------------------------------------------------------------------
    # Modo cine (pantalla completa)
    # ------------------------------------------------------------------
    @property
    def embedded(self) -> bool:
        return self._embedded

    def set_cinema_mode(self, on: bool):
        """La ventana principal avisa al entrar/salir de pantalla completa.
        En modo cine no se ve nada más que el video: los controles vuelven
        al mover el mouse y se esconden solos a los 3 s."""
        self._cinema = on
        app = QApplication.instance()
        if on:
            if app is not None:
                app.installEventFilter(self)
            self.controls.hide()
            self.setCursor(Qt.BlankCursor)
            self.setFocusPolicy(Qt.StrongFocus)
            self.setFocus(Qt.OtherFocusReason)
            self._cinema_hide_timer.stop()
        else:
            if app is not None:
                app.removeEventFilter(self)
            self._cinema_hide_timer.stop()
            self.controls.show()
            self.unsetCursor()

    def eventFilter(self, obj, event):
        # Cualquier movimiento del mouse durante el modo cine devuelve
        # los controles (y reinicia el contador para esconderlos).
        if self._cinema and event.type() == QEvent.MouseMove:
            self._show_controls_temporarily()
        return super().eventFilter(obj, event)

    def _show_controls_temporarily(self):
        if not self._cinema:
            return
        if not self.controls.isVisible():
            self.controls.show()
            self.unsetCursor()
        self._cinema_hide_timer.start()

    def _hide_controls_cinema(self):
        if not self._cinema:
            return
        self.controls.hide()
        self.setCursor(Qt.BlankCursor)
        # Si el foco quedó en un botón de los controles, devolverlo al
        # reproductor para que sigan andando los atajos (Espacio, F, Esc).
        self.setFocus(Qt.OtherFocusReason)

    def mouseMoveEvent(self, event):
        if self._cinema:
            self._show_controls_temporarily()
        super().mouseMoveEvent(event)

    def _set_controls_enabled(self, enabled: bool):
        for w in (
            self.play_btn, self.stop_btn, self.back10_btn, self.fwd10_btn,
            self.sub_btn, self.folder_subs_btn, self.online_subs_btn, self.volume_slider,
            self.fullscreen_btn, self.seek_slider,
        ):
            w.setEnabled(enabled)

    # ------------------------------------------------------------------
    def _ensure_mpv(self) -> bool:
        if self._embedded:
            return True
        if self._mpv and self._mpv.is_running():
            return True
        if not MPV_AVAILABLE:
            self.error_occurred.emit(
                "No se encontró el programa 'mpv'. Instalalo con: brew install mpv"
            )
            return False
        self._mpv = MpvIPCPlayer(
            cache_secs=cache_secs(self._config),
            cache_max_mb=cache_max_mb(self._config),
        )
        self._eof_callback_registered = False
        self._seek_callback_registered = False
        return True

    def _use_external_fallback(self) -> bool:
        """Si libmpv falla al arrancar, intenta el mpv externo."""
        if not MPV_AVAILABLE:
            return False
        self._embedded = False
        self._mpv = None
        self._idle_text = self.IDLE_TEXT_EXTERNAL
        self.info_label.setText(self._idle_text)
        self.stage.setCurrentWidget(self.idle_page)
        return True

    # ------------------------------------------------------------------
    def play(self, url: str, title: str = "", start_at: float = 0.0,
             subtitle_urls: list | None = None):
        if not (self._embedded or self._ensure_mpv()):
            return
        self._current_title = title or url
        self.current_url = url
        self._paused = False
        self.play_btn.setText("⏸")
        self._pending_start_at = 0.0
        self._reset_stall_watch()
        self._apply_cache_prefs()

        if self._embedded and self.video is not None:
            self.stage.setCurrentWidget(self.video)
            self.video.setFocus(Qt.OtherFocusReason)
            self.info_label.setText(f"🎬 Reproduciendo:\n{self._current_title}")
            already_running = self.video.is_running()
            ok = self.video.load(url) if already_running else self.video.start(url)
            if not ok:
                if self._use_external_fallback():
                    self.play(url, title, start_at=start_at,
                              subtitle_urls=subtitle_urls)
                else:
                    self.stage.setCurrentWidget(self.idle_page)
                    self.error_occurred.emit(
                        "No se pudo iniciar el reproductor embebido.\n\n"
                        "Detalle: " + (self.video.last_error() or "desconocido")
                    )
                return
            self._apply_sub_prefs()
            if subtitle_urls:
                for i, sub_url in enumerate(subtitle_urls):
                    self.video.add_subtitle(sub_url, select=(i == 0))
            if start_at and start_at > 1:
                self._pending_start_at = start_at
                # El evento file-loaded lo aplica (ver _on_embedded_file_loaded).
            return

        # --- Backend externo (ventana de mpv aparte) -------------------
        self.stage.setCurrentWidget(self.idle_page)
        self.info_label.setText(
            f"🎬 Reproduciendo en la ventana de mpv:\n{self._current_title}"
        )

        already_running = self._mpv.is_running()
        if already_running:
            self._mpv.load(url, title=self._current_title)
        else:
            ok = self._mpv.start(url, title=self._current_title)
            if not ok:
                detail = self._mpv.last_error or "(mpv no dio más detalles)"
                self.error_occurred.emit(
                    f"No se pudo arrancar mpv.\n\nDetalle: {detail}"
                )
                return

        if not self._eof_callback_registered:
            # "eof-reached" ya lo observa mpv_ipc.start() por defecto;
            # acá solo enganchamos nuestro callback (una sola vez por
            # proceso de mpv, no en cada video, para no acumular
            # callbacks duplicados al pasar de un video a otro).
            self._mpv.on_property("eof-reached", self._on_eof_reached)
            self._mpv.on_property("pause", self._pause_state_signal.emit)
            # "end-file" con reason="error" es como mpv avisa que un
            # archivo puntual falló al cargar DESPUÉS de que el proceso
            # ya arrancó bien (ej. timeout de red con el servidor) — a
            # diferencia de una falla de arranque, esto antes quedaba en
            # silencio total (ventana de mpv vacía, sin ningún aviso).
            self._mpv.on_event("end-file", self._on_end_file)
            self._eof_callback_registered = True

        self._apply_sub_prefs()
        if subtitle_urls:
            for i, sub_url in enumerate(subtitle_urls):
                self._mpv.add_subtitle(sub_url, select=(i == 0))

        if start_at and start_at > 1:
            self._pending_start_at = start_at
            self._arm_resume_seek()

    def _on_embedded_file_loaded(self):
        self._reset_stall_watch()
        if self._pending_start_at and self._pending_start_at > 1:
            self.video.seek(self._pending_start_at, absolute=True)
            self._pending_start_at = 0.0

    # ------------------------------------------------------------------
    # Preferencias en caliente (caché y subtítulos)
    # ------------------------------------------------------------------
    def _apply_cache_prefs(self):
        target = self.video if self._embedded else self._mpv
        if target is None:
            return
        target.set_cache_options(
            cache_secs(self._config), cache_max_mb(self._config)
        )

    def _apply_sub_prefs(self):
        if not self._mpv:
            return
        try:
            self._mpv.set_property("sub-font-size", str(self._sub_size))
            self._mpv.set_property("sub-color", self._sub_color)
            self._mpv.set_property("sub-outline-color", DEFAULT_SUB_OUTLINE)
            self._mpv.set_property("sub-outline-size", "3")
            # Aplica también a subtítulos ASS/SSA (que suelen traer sus
            # propios estilos y, sin esto, ignoran tamaño y color).
            self._mpv.set_property("sub-ass-override", "force")
        except Exception:
            pass

    def _save_sub_prefs(self):
        if not self._config:
            return
        self._config.set("sub_font_size", self._sub_size)
        self._config.set("sub_color", self._sub_color)

    def refresh_preferences(self):
        """Lee de nuevo config.json y aplica los cambios sin reiniciar."""
        self._sub_size = sub_font_size(self._config)
        self._sub_color = sub_color(self._config)
        self._apply_sub_prefs()
        self._apply_cache_prefs()

    def _osd(self, text: str, duration_ms: int = 1800):
        if self._mpv:
            try:
                self._mpv.show_text(text, duration_ms)
            except Exception:
                pass

    def change_sub_size(self, delta: int):
        new_size = max(
            MIN_SUB_FONT_SIZE,
            min(MAX_SUB_FONT_SIZE, self._sub_size + int(delta)),
        )
        if new_size == self._sub_size:
            limite = "máximo" if delta > 0 else "mínimo"
            self._osd(f"Tamaño de subtítulos: {limite} ({new_size})")
            return
        self._sub_size = new_size
        self._save_sub_prefs()
        self._apply_sub_prefs()
        self._osd(f"Subtítulos: {new_size}")

    def cycle_sub_color(self):
        colores = [hex_value for _name, hex_value in SUB_COLORS]
        try:
            index = colores.index(self._sub_color)
        except ValueError:
            index = -1
        index = (index + 1) % len(SUB_COLORS)
        name, self._sub_color = SUB_COLORS[index]
        self._save_sub_prefs()
        self._apply_sub_prefs()
        self._osd(f"Color de subtítulos: {name}")

    # ------------------------------------------------------------------
    # Vigilante de trabas
    # ------------------------------------------------------------------
    def _reset_stall_watch(self):
        self._watch_pos = None
        self._watch_since = time.monotonic()
        self._last_recovery = 0.0
        self._recover_attempts = 0

    def _tick_stall_watch(self, pos: float, paused: bool, buffering: bool):
        now = time.monotonic()
        # Mientras mpv dice que está buffereando o pausado, es normal que
        # el tiempo no avance: no lo tratamos como traba.
        if paused or buffering or not pos:
            self._watch_pos = pos
            self._watch_since = now
            return
        if self._watch_pos is None or abs(pos - self._watch_pos) > 0.2:
            self._watch_pos = pos
            self._watch_since = now
            self._recover_attempts = 0
            return
        if now - self._watch_since < 12 or now - self._last_recovery < 25:
            return
        self._last_recovery = now
        self._watch_since = now
        self._recover_stall(pos)

    def _recover_stall(self, pos: float):
        if not (self._mpv and self._mpv.is_running()):
            return
        if self.current_url is None:
            return
        if self._recover_attempts == 0:
            # Primer intento: pedir el mismo punto de nuevo suele
            # destrabar un demuxer que quedó esperando datos.
            self._osd("Video trabado: reconectando…", 4000)
            self._mpv.seek(max(0.0, pos), absolute=True)
            self._recover_attempts = 1
            return
        # Segundo intento: recargar el archivo desde la posición actual.
        self._osd("Reintentando el video desde el mismo punto…", 5000)
        self._recover_attempts = 0
        self._pending_start_at = max(0.0, pos)
        if self._embedded and self.video is not None:
            self.video.load(self.current_url)
        else:
            self._mpv.load(self.current_url, title=self._current_title)
            self._arm_resume_seek()

    def _on_pause_changed(self, value):
        # Si el usuario pausa/reanuda desde el propio video o desde mpv,
        # el botón de la app tiene que reflejarlo (antes solo cambiaba al
        # usar el botón de acá).
        paused = bool(value)
        self._paused = paused
        self.play_btn.setText("▶" if paused else "⏸")

    def _on_end_file(self, msg: dict):
        # Puede correr en el hilo lector del socket IPC o en el hilo de
        # eventos de libmpv; emitir una señal de Qt desde ahí es seguro.
        if msg.get("reason") == "error":
            self.error_occurred.emit(
                "mpv no pudo cargar este video.\n\n"
                "Suele ser un problema de conexión con el servidor "
                "(lento o caído en este momento). Probá de nuevo en un "
                "rato, o con otro video para descartar que sea un "
                "archivo puntual."
            )

    def _on_eof_reached(self, value):
        # Corre en el hilo lector del socket IPC (modo externo).
        if value:
            self.track_finished.emit()

    def _arm_resume_seek(self):
        if self._seek_callback_registered:
            # El callback es uno solo por proceso de mpv y lee siempre el
            # valor pendiente actual; registrar uno nuevo por cada video
            # acumulaba callbacks y podía saltar a una posición vieja.
            return

        def _apply_pending_seek(*_args):
            if self._pending_start_at and self._mpv and self._mpv.is_running():
                self._mpv.seek(self._pending_start_at, absolute=True)
                self._pending_start_at = 0.0

        # "seekable" puede no volver a emitirse si mpv ya estaba en True
        # al cargar el siguiente archivo; "file-loaded" garantiza el
        # salto de resume en cada video nuevo.
        self._mpv.on_property("seekable", _apply_pending_seek)
        self._mpv.on_event("file-loaded", _apply_pending_seek)
        self._seek_callback_registered = True

    def current_progress(self) -> tuple[float, float]:
        if not self._mpv or not self._mpv.is_running():
            return 0.0, 0.0
        pos = self._mpv.get_cached_property("time-pos", 0.0) or 0.0
        dur = self._mpv.get_cached_property("duration", 0.0) or 0.0
        return pos, dur

    def toggle_pause(self):
        if not self._mpv or not self._mpv.is_running():
            return
        self._paused = not bool(self._mpv.get_cached_property("pause", self._paused))
        self._mpv.play_pause(self._paused)
        self.play_btn.setText("▶" if self._paused else "⏸")

    def stop(self):
        """Detiene la reproducción y vuelve al cartel de inicio."""
        if self._mpv:
            self._mpv.terminate()
        if self._embedded and self.video is not None:
            self._mpv = self.video
            self.stage.setCurrentWidget(self.idle_page)
        elif self._embedded:
            self.stage.setCurrentWidget(self.idle_page)
        else:
            self._mpv = None
            self.stage.setCurrentWidget(self.idle_page)
        self.info_label.setText(self._idle_text)
        self.seek_slider.setValue(0)
        self.time_label.setText("0:00")
        self.duration_label.setText("0:00")
        self.current_url = None
        self._pending_start_at = 0.0
        self._paused = False
        self.play_btn.setText("⏸")
        self._eof_callback_registered = False
        self._seek_callback_registered = False
        self._reset_stall_watch()

    def seek_relative(self, seconds: float):
        if self._mpv and self._mpv.is_running():
            self._mpv.seek(seconds, absolute=False)

    def _toggle_subs(self):
        if self._mpv and self._mpv.is_running():
            self._mpv.set_sub_visibility(self.sub_btn.isChecked())

    def add_local_subtitle(self, path: str):
        """Agrega y activa un subtítulo descargado (archivo local)."""
        if self._mpv and self._mpv.is_running():
            self._mpv.add_subtitle(path, select=True)
            self.sub_btn.setChecked(True)
            self._mpv.set_sub_visibility(True)

    def add_subtitle_url(self, url: str, select: bool = True):
        """Agrega un subtítulo remoto (misma carpeta del video) sin
        interrumpir la reproducción. Con varios subtítulos conviene
        select=True solo en el primero, para no terminar seleccionando
        el último de la lista de forma arbitraria."""
        if self._mpv and self._mpv.is_running():
            self._mpv.add_subtitle(url, select=select)
            if select:
                self.sub_btn.setChecked(True)
                self._mpv.set_sub_visibility(True)

    def replace_subtitles(self, urls: list[str]):
        """Carga los subtítulos elegidos por el usuario en el pop-up,
        dejando el primero como pista activa. Las pistas que ya estaban
        cargadas (carga automática) no se pueden listar/borrar sin
        respuestas, así que quedan como alternativas y se pueden
        ciclar dentro de mpv con j/k."""
        if not (self._mpv and self._mpv.is_running()):
            return
        for i, url in enumerate(urls):
            self._mpv.add_subtitle(url, select=(i == 0))
        if urls:
            self.sub_btn.setChecked(True)
            self._mpv.set_sub_visibility(True)
        else:
            # eligió "sin subtítulos": oculta los que ya estaban cargados
            self.sub_btn.setChecked(False)
            self._mpv.set_sub_visibility(False)

    def current_title(self) -> str:
        return self._current_title

    def _on_volume_changed(self, value: int):
        if self._mpv and self._mpv.is_running():
            self._mpv.set_volume(value)

    def _toggle_fullscreen(self):
        if self._embedded:
            win = self.window()
            if win.isFullScreen():
                win.showNormal()
                self.fullscreen_btn.setText("⛶ Pantalla completa")
            else:
                win.showFullScreen()
                self.fullscreen_btn.setText("⛶ Salir de pantalla completa")
            return
        # Modo externo: pantalla completa de la ventana de mpv.
        if self._mpv and self._mpv.is_running():
            self._mpv.toggle_fullscreen()

    def _exit_fullscreen(self):
        if self._embedded and self.window().isFullScreen():
            self.window().showNormal()
            self.fullscreen_btn.setText("⛶ Pantalla completa")

    def _on_seek_start(self):
        self._seeking = True

    def _on_seek_end(self):
        if self._mpv and self._mpv.is_running() and self._duration:
            frac = self.seek_slider.value() / 1000.0
            self._mpv.seek(frac * self._duration, absolute=True)
        self._seeking = False

    def _refresh_ui(self):
        if not self._mpv or not self._mpv.is_running() or self._seeking:
            return
        pos = self._mpv.get_cached_property("time-pos", 0.0) or 0.0
        dur = self._mpv.get_cached_property("duration", 0.0) or 0.0
        self._duration = dur
        self.time_label.setText(_fmt_time(pos))
        self.duration_label.setText(_fmt_time(dur))
        if dur:
            self.seek_slider.setValue(int((pos / dur) * 1000))
        if dur > 0:
            finished = bool(self._mpv.get_cached_property("eof-reached", False))
            self._tick_stall_watch(
                float(pos),
                bool(self._mpv.get_cached_property("pause", False)) or finished,
                bool(self._mpv.get_cached_property("paused-for-cache", False)),
            )

    def shutdown(self):
        self._ui_timer.stop()
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        if self._embedded and self.video is not None:
            self.video.shutdown()
            self._mpv = None
        elif self._mpv:
            self._mpv.terminate()
            self._mpv = None
