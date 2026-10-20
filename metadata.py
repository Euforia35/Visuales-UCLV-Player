"""
metadata.py
-----------
Caché local de metadatos enriquecidos por carpeta (lo que devolvió TMDb
una vez que se buscó, más lo parseado del nombre del archivo).

El servidor no expone una API de metadatos, así que la estrategia es:
primera visita a una carpeta → se busca en TMDb en background (si hay
API key) → queda guardado acá para siempre → la UI nunca vuelve a esperar.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from naming import clean_display_title, parse_year


@dataclass
class MediaMeta:
    """Metadatos de una carpeta/película/serie."""
    title: str = ""
    year: str = ""
    runtime_min: int = 0
    genres: list[str] = field(default_factory=list)
    rating: float = 0.0
    overview: str = ""
    poster_url: str = ""
    backdrop_url: str = ""
    media_type: str = "movie"
    fetched_at: float = 0.0

    def chips(self) -> list[str]:
        """Chips para la vista de detalle: año · duración · ★ rating · géneros."""
        out: list[str] = []
        if self.year:
            out.append(self.year)
        if self.runtime_min:
            from naming import format_runtime
            out.append(format_runtime(self.runtime_min))
        if self.rating > 0:
            out.append(f"★ {self.rating:.1f}")
        out.extend(self.genres[:3])
        return out


def meta_from_tmdb_info(info: dict) -> MediaMeta:
    return MediaMeta(
        title=info.get("title", ""),
        year=info.get("year", ""),
        runtime_min=info.get("runtime_min", 0) or 0,
        genres=list(info.get("genres") or []),
        rating=float(info.get("rating") or 0),
        overview=info.get("overview", ""),
        poster_url=info.get("poster_url", ""),
        backdrop_url=info.get("backdrop_url", ""),
        media_type=info.get("media_type", "movie"),
        fetched_at=time.time(),
    )


def local_guess_meta(folder_name: str) -> MediaMeta:
    """Metadatos mínimos sin red: título y año parseados del nombre."""
    return MediaMeta(
        title=clean_display_title(folder_name),
        year=parse_year(folder_name) or "",
        media_type="movie",
    )


class MetadataStore:
    """JSON en disco: {folder_url: MediaMeta serializada}. Hilos comunes
    (el executor de background escribe, la UI lee), con lock simple."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                self._data = json.loads(self.path.read_text())
            except Exception:
                self._data = {}

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2))
        except Exception:
            pass

    # ------------------------------------------------------------------
    def get(self, folder_url: str) -> MediaMeta | None:
        with self._lock:
            raw = self._data.get(folder_url)
        if not raw:
            return None
        known = {f.name for f in MediaMeta.__dataclass_fields__.values()}
        return MediaMeta(**{k: v for k, v in raw.items() if k in known})

    def put(self, folder_url: str, meta: MediaMeta):
        with self._lock:
            self._data[folder_url] = asdict(meta)
            self._save()

    def has(self, folder_url: str) -> bool:
        with self._lock:
            return folder_url in self._data

    def remove(self, folder_url: str):
        """Borra la ficha cacheada de una carpeta (ej. cuando el usuario
        corrige el nombre y la búsqueda anterior ya no vale)."""
        with self._lock:
            if folder_url in self._data:
                del self._data[folder_url]
                self._save()

    def __len__(self):
        with self._lock:
            return len(self._data)


class TitleOverrideStore:
    """Título de búsqueda corregido A MANO por el usuario, por carpeta.

    A veces la carpeta del servidor tiene el nombre mal escrito
    ("The mandalorian X1") y TMDb no encuentra nada. El usuario puede
    escribir el nombre correcto desde la vista de detalle; se guarda acá
    (JSON en disco) y se usa SIEMPRE en lugar del nombre de la carpeta
    para buscar la ficha."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._data: dict[str, str] = {}
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text())
                if isinstance(data, dict):
                    self._data = {k: str(v) for k, v in data.items()}
            except Exception:
                self._data = {}

    def _save(self):
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2))
        except Exception:
            pass

    def get(self, folder_url: str) -> str:
        with self._lock:
            return self._data.get(folder_url, "")

    def set(self, folder_url: str, title: str):
        """Guarda (o borra, si `title` viene vacío) el título corregido."""
        title = (title or "").strip()
        with self._lock:
            if title:
                self._data[folder_url] = title
            else:
                self._data.pop(folder_url, None)
            self._save()

    def clear(self, folder_url: str):
        self.set(folder_url, "")
