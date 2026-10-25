"""
player_prefs.py
---------------
Valores por defecto y helpers de las preferencias del reproductor.

Las preferencias se guardan en el ``config.json`` de la app (ver
``config_store.py``): búfer/caché de video y estilo de subtítulos.
Tanto ``player.py`` como el diálogo de preferencias usan estas mismas
funciones para que los valores nunca se contradigan.
"""

from __future__ import annotations

from config_store import ConfigStore

# --- Caché / búfer de video ------------------------------------------------
# Valores del MVP original: sin límites estrictos en mpv externo.
DEFAULT_CACHE_SECS = 120
DEFAULT_CACHE_MAX_MB = 256
MIN_CACHE_SECS = 30
MAX_CACHE_SECS = 1800
MIN_CACHE_MB = 32
MAX_CACHE_MB = 1024

# --- Subtítulos -------------------------------------------------------------
DEFAULT_SUB_FONT_SIZE = 55
MIN_SUB_FONT_SIZE = 30
MAX_SUB_FONT_SIZE = 120
SUB_FONT_STEP = 5

# mpv usa #AARRGGBB (alfa primero) para los colores de 4 bytes.
SUB_COLORS: list[tuple[str, str]] = [
    ("Blanco", "#FFFFFFFF"),
    ("Amarillo", "#FFFFFF00"),
    ("Cian", "#FF00FFFF"),
    ("Verde", "#FF00FF00"),
    ("Naranja", "#FFFFA500"),
    ("Rosa", "#FFFF69B4"),
    ("Rojo", "#FFFF4040"),
]
DEFAULT_SUB_COLOR = SUB_COLORS[0][1]
DEFAULT_SUB_OUTLINE = "#FF000000"


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def cache_secs(config: ConfigStore | None) -> int:
    value = config.get("video_cache_secs") if config else None
    return _clamp(_as_int(value, DEFAULT_CACHE_SECS), MIN_CACHE_SECS, MAX_CACHE_SECS)


def cache_max_mb(config: ConfigStore | None) -> int:
    value = config.get("video_cache_max_mb") if config else None
    return _clamp(_as_int(value, DEFAULT_CACHE_MAX_MB), MIN_CACHE_MB, MAX_CACHE_MB)


def sub_font_size(config: ConfigStore | None) -> int:
    value = config.get("sub_font_size") if config else None
    return _clamp(_as_int(value, DEFAULT_SUB_FONT_SIZE), MIN_SUB_FONT_SIZE, MAX_SUB_FONT_SIZE)


def sub_color(config: ConfigStore | None) -> str:
    value = (config.get("sub_color") if config else None) or DEFAULT_SUB_COLOR
    if not isinstance(value, str) or len(value) not in (7, 9) or not value.startswith("#"):
        return DEFAULT_SUB_COLOR
    # Normalizamos #RRGGBB -> #FFRRGGBB (opaco) y validamos hexadecimal.
    if len(value) == 7:
        value = "#FF" + value[1:]
    try:
        int(value[1:], 16)
    except ValueError:
        return DEFAULT_SUB_COLOR
    return value.upper()
