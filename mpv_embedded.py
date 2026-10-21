"""
mpv_embedded.py
---------------
Reproductor embebido usando **libmpv + render API OpenGL** dentro de un
QOpenGLWidget. A diferencia del mpv como proceso aparte, acá el video se
dibuja dentro de la propia ventana de la app (sin ventana externa ni
``--wid``, que en macOS no existe).

La integración es la misma que usan clientes nativos como IINA: se crea
un ``mpv_render_context`` sobre el contexto OpenGL de Qt y en cada
``paintGL`` se le pide a libmpv que dibuje el frame actual en el FBO del
widget. Todo el control (cargar, pausar, seek, volumen, subtítulos) se
hace por la API de libmpv, sin sockets IPC.

Si libmpv no está disponible (por ejemplo, una instalación de mpv sin
la librería compartida), ``LIBMPV_AVAILABLE`` queda en False y la app
sigue usando el reproductor externo de ``mpv_ipc.py``.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import locale
import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QColor, QPainter, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QSizePolicy

# ---------------------------------------------------------------------------
# Carga de libmpv
# ---------------------------------------------------------------------------
_CANDIDATE_LIBS = [
    "/opt/homebrew/lib/libmpv.dylib",
    "/usr/local/lib/libmpv.dylib",
    "/opt/homebrew/opt/mpv/lib/libmpv.dylib",
    "/usr/local/opt/mpv/lib/libmpv.dylib",
]


def find_libmpv() -> str | None:
    """Ruta a libmpv, o None si no está instalada."""
    env = os.environ.get("VISUALES_LIBMPV")
    if env and Path(env).exists():
        return env
    for path in _CANDIDATE_LIBS:
        if Path(path).exists():
            return path
    name = ctypes.util.find_library("mpv")
    if name:
        return name
    return None


LIBMPV_PATH = find_libmpv()
LIBMPV_AVAILABLE = LIBMPV_PATH is not None

# ---------------------------------------------------------------------------
# Constantes / estructuras de la API C de libmpv
# ---------------------------------------------------------------------------
MPV_FORMAT_NONE = 0
MPV_FORMAT_STRING = 1
MPV_FORMAT_FLAG = 3
MPV_FORMAT_INT64 = 4
MPV_FORMAT_DOUBLE = 5

MPV_EVENT_NONE = 0
MPV_EVENT_SHUTDOWN = 1
MPV_EVENT_FILE_LOADED = 8
MPV_EVENT_END_FILE = 7
MPV_EVENT_PROPERTY_CHANGE = 22

MPV_RENDER_PARAM_API_TYPE = 1
MPV_RENDER_PARAM_OPENGL_INIT_PARAMS = 2
MPV_RENDER_PARAM_OPENGL_FBO = 3
MPV_RENDER_PARAM_FLIP_Y = 4
MPV_RENDER_PARAM_INVALID = 0

MPV_END_FILE_REASON_EOF = 0
MPV_END_FILE_REASON_ERROR = 4

c_void_p = ctypes.c_void_p
c_int = ctypes.c_int
c_char_p = ctypes.c_char_p
c_double = ctypes.c_double
c_int64 = ctypes.c_int64


class _OpenGLInitParams(ctypes.Structure):
    _fields_ = [
        ("get_proc_address", c_void_p),
        ("get_proc_address_ctx", c_void_p),
        ("extra_exts", c_char_p),
    ]


class _OpenGLFBO(ctypes.Structure):
    _fields_ = [
        ("fbo", c_int),
        ("w", c_int),
        ("h", c_int),
        ("internal_format", c_int),
    ]


class _RenderParam(ctypes.Structure):
    _fields_ = [("type", c_int), ("data", c_void_p)]


class _Event(ctypes.Structure):
    _fields_ = [
        ("event_id", c_int),
        ("error", c_int),
        ("reply_userdata", ctypes.c_uint64),
        ("data", c_void_p),
    ]


class _EventProperty(ctypes.Structure):
    _fields_ = [("name", c_char_p), ("format", c_int), ("data", c_void_p)]


class _EventEndFile(ctypes.Structure):
    _fields_ = [
        ("reason", c_int),
        ("error", c_int),
        ("playlist_entry_id", c_int64),
        ("playlist_insert_id", c_int64),
        ("playlist_insert_num_entries", c_int),
    ]


_GET_PROC = ctypes.CFUNCTYPE(c_void_p, c_void_p, c_char_p)
_UPDATE_CB = ctypes.CFUNCTYPE(None, c_void_p)


def _load_lib(path: str):
    lib = ctypes.CDLL(path)
    lib.mpv_create.restype = c_void_p
    lib.mpv_initialize.argtypes = [c_void_p]
    lib.mpv_initialize.restype = c_int
    lib.mpv_set_option_string.argtypes = [c_void_p, c_char_p, c_char_p]
    lib.mpv_set_option_string.restype = c_int
    lib.mpv_set_property_string.argtypes = [c_void_p, c_char_p, c_char_p]
    lib.mpv_set_property_string.restype = c_int
    lib.mpv_get_property.argtypes = [c_void_p, c_char_p, c_int, c_void_p]
    lib.mpv_get_property.restype = c_int
    lib.mpv_command.argtypes = [c_void_p, ctypes.POINTER(c_char_p)]
    lib.mpv_command.restype = c_int
    lib.mpv_observe_property.argtypes = [c_void_p, ctypes.c_uint64, c_char_p, c_int]
    lib.mpv_observe_property.restype = c_int
    lib.mpv_wait_event.argtypes = [c_void_p, c_double]
    lib.mpv_wait_event.restype = ctypes.POINTER(_Event)
    lib.mpv_terminate_destroy.argtypes = [c_void_p]
    lib.mpv_render_context_create.argtypes = [
        ctypes.POINTER(c_void_p), c_void_p, ctypes.POINTER(_RenderParam)
    ]
    lib.mpv_render_context_create.restype = c_int
    lib.mpv_render_context_set_update_callback.argtypes = [
        c_void_p, _UPDATE_CB, c_void_p
    ]
    lib.mpv_render_context_render.argtypes = [
        c_void_p, ctypes.POINTER(_RenderParam)
    ]
    lib.mpv_render_context_render.restype = c_int
    lib.mpv_render_context_update.argtypes = [c_void_p]
    lib.mpv_render_context_update.restype = ctypes.c_uint64
    lib.mpv_render_context_report_swap.argtypes = [c_void_p]
    lib.mpv_render_context_free.argtypes = [c_void_p]
    return lib


class _FrameBridge(QObject):
    """Puente hilo de mpv -> hilo GUI para repintar el widget."""

    frame_ready = Signal()


def _default_surface_format():
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(0)
    fmt.setStencilBufferSize(0)
    fmt.setSwapInterval(1)
    return fmt


class EmbeddedMpvPlayer(QOpenGLWidget):
    """Widget de video + controlador libmpv.

    Expone a propósito la misma interfaz que ``MpvIPCPlayer`` (start,
    load, play_pause, seek, add_subtitle, get_cached_property, on_event,
    on_property, …) para que ``player.py`` pueda usar cualquiera de los
    dos backends sin cambiar el resto de la app.
    """

    error_occurred = Signal(str)
    track_finished = Signal()
    pause_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setFormat(_default_surface_format())
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setStyleSheet("background: black;")

        self._lib = _load_lib(LIBMPV_PATH) if LIBMPV_AVAILABLE else None
        self._handle: int | None = None
        self._render_ctx = c_void_p()
        self._running = False
        self._stopping = False
        self._pending_url: str | None = None
        self._error = ""
        self._bridge = _FrameBridge()
        self._bridge.frame_ready.connect(self.update, Qt.QueuedConnection)
        self._update_cb = _UPDATE_CB(self._on_mpv_update) if self._lib else None
        self._get_proc_cb = _GET_PROC(self._get_proc_address) if self._lib else None
        self._event_thread: threading.Thread | None = None
        self._event_stop = threading.Event()
        self._prop_callbacks: dict[str, list] = {}
        self._event_callbacks: dict[str, list] = {}
        self._last_eof = False
        self._gl_cleanup_connected = False
        self._self_gl = ctypes.CDLL(None)
        self._gl_framework = None
        try:
            self._gl_framework = ctypes.CDLL(
                "/System/Library/Frameworks/OpenGL.framework/OpenGL"
            )
        except OSError:
            pass

        # Evita el clásico crash de mpv cuando el locale usa coma decimal.
        try:
            locale.setlocale(locale.LC_NUMERIC, "C")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Ciclo de vida GL
    # ------------------------------------------------------------------
    def initializeGL(self):
        if self._render_ctx:
            return
        if not self._ensure_handle():
            return
        locale.setlocale(locale.LC_NUMERIC, "C")
        init_params = _OpenGLInitParams(
            ctypes.cast(self._get_proc_cb, c_void_p), None, None
        )
        params = (_RenderParam * 3)(
            _RenderParam(
                MPV_RENDER_PARAM_API_TYPE,
                ctypes.cast(c_char_p(b"opengl"), c_void_p),
            ),
            _RenderParam(
                MPV_RENDER_PARAM_OPENGL_INIT_PARAMS,
                ctypes.cast(ctypes.pointer(init_params), c_void_p),
            ),
            _RenderParam(MPV_RENDER_PARAM_INVALID, None),
        )
        rc = self._lib.mpv_render_context_create(
            ctypes.byref(self._render_ctx), self._handle, params
        )
        if rc < 0:
            self._error = f"mpv_render_context_create falló ({rc})"
            self.error_occurred.emit(self._error)
            self._render_ctx = c_void_p()
            return
        self._lib.mpv_render_context_set_update_callback(
            self._render_ctx, self._update_cb, None
        )
        context = self.context()
        if context is not None and not self._gl_cleanup_connected:
            context.aboutToBeDestroyed.connect(self._cleanup_gl)
            self._gl_cleanup_connected = True
        if self._pending_url:
            url, self._pending_url = self._pending_url, None
            self._send_load(url)

    def _cleanup_gl(self):
        if not self._render_ctx:
            return
        try:
            self.makeCurrent()
            self._lib.mpv_render_context_free(self._render_ctx)
        except Exception:
            pass
        finally:
            self._render_ctx = c_void_p()
            try:
                self.doneCurrent()
            except Exception:
                pass

    def paintGL(self):
        # Fondo negro (también cubre el caso de que mpv no tenga frame).
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0))
        painter.end()
        if not self._render_ctx or not self._handle:
            return
        fbo = _OpenGLFBO(
            self.defaultFramebufferObject(),
            max(1, int(self.width() * self.devicePixelRatioF())),
            max(1, int(self.height() * self.devicePixelRatioF())),
            0,
        )
        flip = c_int(1)
        params = (_RenderParam * 3)(
            _RenderParam(
                MPV_RENDER_PARAM_OPENGL_FBO,
                ctypes.cast(ctypes.pointer(fbo), c_void_p),
            ),
            _RenderParam(
                MPV_RENDER_PARAM_FLIP_Y,
                ctypes.cast(ctypes.pointer(flip), c_void_p),
            ),
            _RenderParam(MPV_RENDER_PARAM_INVALID, None),
        )
        rc = self._lib.mpv_render_context_render(self._render_ctx, params)
        if rc < 0 and rc != -15:  # -15 = MPV_ERROR_UNINITIALIZED
            self._error = f"mpv_render_context_render falló ({rc})"
        self._lib.mpv_render_context_report_swap(self._render_ctx)

    def _on_mpv_update(self, _data):
        # Corre en el hilo de render de mpv; la señal se encola sola.
        self._bridge.frame_ready.emit()

    def _get_proc_address(self, _ctx, name):
        text = name.decode()
        for library in (self._self_gl, self._gl_framework):
            if library is None:
                continue
            try:
                func = getattr(library, text)
            except AttributeError:
                continue
            return ctypes.cast(func, c_void_p).value
        return 0

    # ------------------------------------------------------------------
    # Handle / eventos
    # ------------------------------------------------------------------
    def _ensure_handle(self) -> bool:
        if self._handle:
            return True
        if not self._lib:
            self._error = "libmpv no está instalada"
            return False
        self._handle = self._lib.mpv_create()
        if not self._handle:
            self._error = "mpv_create devolvió NULL"
            return False
        options = {
            "vo": "libmpv",
            "hwdec": "auto-safe",
            "keep-open": "yes",
            "idle": "yes",
            "osc": "no",
            "input-default-bindings": "no",
            "input-vo-keyboard": "no",
            "terminal": "no",
            "msg-level": "all=warn",
            "cache": "yes",
            "demuxer-max-bytes": "150MiB",
            "demuxer-readahead-secs": "300",
            "network-timeout": "60",
        }
        for key, value in options.items():
            rc = self._lib.mpv_set_option_string(
                self._handle, key.encode(), value.encode()
            )
            if rc < 0:
                # No abortamos por una opción desconocida: mpv sigue
                # andando con el resto (mismo criterio que en mpv_ipc).
                continue
        rc = self._lib.mpv_initialize(self._handle)
        if rc < 0:
            self._error = f"mpv_initialize falló ({rc})"
            self._lib.mpv_terminate_destroy(self._handle)
            self._handle = None
            return False
        for name, fmt in (
            ("pause", MPV_FORMAT_FLAG),
            ("eof-reached", MPV_FORMAT_FLAG),
            ("seekable", MPV_FORMAT_FLAG),
        ):
            self._lib.mpv_observe_property(
                self._handle, 0, name.encode(), fmt
            )
        self._start_event_thread()
        return True

    def _start_event_thread(self):
        if self._event_thread and self._event_thread.is_alive():
            return
        self._event_stop.clear()
        self._event_thread = threading.Thread(
            target=self._event_loop, name="mpv-events", daemon=True
        )
        self._event_thread.start()

    def _event_loop(self):
        handle = self._handle
        if not handle:
            return
        while not self._event_stop.is_set():
            event = self._lib.mpv_wait_event(handle, 0.1)
            if not event:
                continue
            ev = event.contents
            if ev.event_id == MPV_EVENT_NONE:
                continue
            if ev.event_id == MPV_EVENT_SHUTDOWN:
                break
            if ev.event_id == MPV_EVENT_PROPERTY_CHANGE:
                if not ev.data:
                    continue
                prop = ctypes.cast(ev.data, ctypes.POINTER(_EventProperty)).contents
                if not prop.name:
                    continue
                name = prop.name.decode()
                value = None
                if prop.data:
                    if prop.format == MPV_FORMAT_FLAG:
                        value = bool(ctypes.cast(prop.data, ctypes.POINTER(c_int)).contents.value)
                    elif prop.format == MPV_FORMAT_DOUBLE:
                        value = ctypes.cast(prop.data, ctypes.POINTER(c_double)).contents.value
                    elif prop.format == MPV_FORMAT_INT64:
                        value = ctypes.cast(prop.data, ctypes.POINTER(c_int64)).contents.value
                    elif prop.format == MPV_FORMAT_STRING:
                        raw = ctypes.cast(prop.data, ctypes.POINTER(c_char_p)).contents.value
                        value = raw.decode(errors="replace") if raw else ""
                if name == "eof-reached":
                    value = bool(value)
                    if value and not self._last_eof:
                        self._last_eof = True
                        self.track_finished.emit()
                    elif not value:
                        self._last_eof = False
                elif name == "pause":
                    self.pause_changed.emit(bool(value))
                for callback in list(self._prop_callbacks.get(name, [])):
                    try:
                        callback(value)
                    except Exception:
                        pass
            elif ev.event_id == MPV_EVENT_END_FILE:
                reason = ""
                if ev.data:
                    data = ctypes.cast(ev.data, ctypes.POINTER(_EventEndFile)).contents
                    if data.reason == MPV_END_FILE_REASON_ERROR:
                        reason = "error"
                    elif data.reason == MPV_END_FILE_REASON_EOF:
                        reason = "eof"
                if reason == "error":
                    self._error = "mpv no pudo cargar el video"
                for callback in list(self._event_callbacks.get("end-file", [])):
                    try:
                        callback({"reason": reason, "error": ev.error})
                    except Exception:
                        pass
            elif ev.event_id == MPV_EVENT_FILE_LOADED:
                self._running = True
                self._last_eof = False
                for callback in list(self._event_callbacks.get("file-loaded", [])):
                    try:
                        callback()
                    except Exception:
                        pass

    # ------------------------------------------------------------------
    # Interfaz compatible con MpvIPCPlayer
    # ------------------------------------------------------------------
    def is_running(self) -> bool:
        return bool(self._handle) and self._running

    def start(self, url: str, title: str = "") -> bool:
        if not self._ensure_handle():
            self.error_occurred.emit(
                "No se pudo inicializar libmpv.\n\nDetalle: " + (self._error or "desconocido")
            )
            return False
        self._running = True
        self._last_eof = False
        self.show()
        if not self._render_ctx:
            # Todavía no se inicializó el contexto OpenGL: guardamos la
            # URL y se carga apenas initializeGL cree el render context.
            self._pending_url = url
            return True
        self._send_load(url)
        return True

    def load(self, url: str, title: str = "") -> bool:
        if not self._handle:
            return self.start(url, title)
        self._running = True
        self._last_eof = False
        self._send_load(url)
        return True

    def _send_load(self, url: str):
        # "replace" corta el video anterior en vez de encolarlo.
        self._command(b"loadfile", url.encode(), b"replace")

    def _command(self, *args: bytes):
        if not self._handle:
            return -1
        array = (c_char_p * (len(args) + 1))(*args, None)
        return self._lib.mpv_command(self._handle, array)

    def _set_property(self, name: str, value: str):
        if not self._handle:
            return
        self._lib.mpv_set_property_string(
            self._handle, name.encode(), str(value).encode()
        )

    def play_pause(self, paused: bool):
        self._set_property("pause", "yes" if paused else "no")

    def seek(self, seconds: float, absolute: bool = True):
        self._command(
            b"seek",
            f"{max(0.0, float(seconds)):.3f}".encode(),
            b"absolute" if absolute else b"relative",
        )

    def set_volume(self, value: int):
        self._set_property("volume", str(int(value)))

    def set_sub_visibility(self, visible: bool):
        self._set_property("sub-visibility", "yes" if visible else "no")

    def add_subtitle(self, url: str, select: bool = True):
        flags = b"select" if select else b"auto"
        self._command(b"sub-add", url.encode(), flags)

    def get_cached_property(self, name: str, default=None):
        if not self._handle:
            return default
        if name in ("pause", "eof-reached", "seekable", "idle-active"):
            value = c_int()
            rc = self._lib.mpv_get_property(
                self._handle, name.encode(), MPV_FORMAT_FLAG, ctypes.byref(value)
            )
            return bool(value.value) if rc >= 0 else default
        if name in ("time-pos", "duration", "volume"):
            value = c_double()
            rc = self._lib.mpv_get_property(
                self._handle, name.encode(), MPV_FORMAT_DOUBLE, ctypes.byref(value)
            )
            return value.value if rc >= 0 else default
        return default

    def on_property(self, name: str, callback):
        self._prop_callbacks.setdefault(name, []).append(callback)

    def on_event(self, name: str, callback):
        self._event_callbacks.setdefault(name, []).append(callback)

    def toggle_fullscreen(self):
        # No-op acá: player.py hace pantalla completa con la ventana de
        # la app (el video es parte de ella, ya no hay ventana de mpv).
        return

    def stop(self):
        self._running = False
        self._pending_url = None
        self._last_eof = False
        if self._handle:
            self._command(b"stop")

    def terminate(self):
        self.stop()

    def shutdown(self):
        self._event_stop.set()
        thread = self._event_thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self._event_thread = None
        self._cleanup_gl()
        if self._handle:
            try:
                self._lib.mpv_terminate_destroy(self._handle)
            except Exception:
                pass
            self._handle = None
        self._running = False
        self._pending_url = None

    def last_error(self) -> str:
        return self._error


def embedded_available() -> bool:
    return LIBMPV_AVAILABLE and os.environ.get("VISUALES_PLAYER", "").lower() != "external"
