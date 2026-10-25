"""
thumbnails.py
-------------
Busca y descarga (con caché en disco y memoria) carátulas/pósters para
carpetas y videos.

Heurística de búsqueda (el servidor no expone una API de metadatos,
así que probamos convenciones típicas de estructuras "listas para Kodi"):

  1. Un archivo hermano con el mismo nombre base y extensión de imagen
     en la MISMA carpeta (ej. "Breaking Bad/" + "Breaking Bad.jpg", o
     "episodio01.mp4" + "episodio01.jpg"). No cuesta una request extra
     de listado porque ya tenemos las entradas de la carpeta actual.
  2. Para carpetas, nombres típicos de Kodi DENTRO de la carpeta:
     poster.jpg, folder.jpg, cover.jpg (y variantes .png/.jpeg/.webp).
     Esto sí es una request HTTP directa (sin listar el directorio),
     que falla silenciosamente (404) si no existe.

Si estas convenciones no calzan con la estructura real del sitio, se
pueden ajustar fácilmente las listas POSTER_CANDIDATE_NAMES / IMAGE_EXTS
de este archivo.
"""

from __future__ import annotations

import hashlib
import io
import json
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin

from PySide6.QtCore import QObject, Signal
from PIL import Image, ImageOps

from apache_index import Entry

IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".webp"]
# Orden de prueba por extensión: los .jpg son por lejos los más comunes,
# así que probamos los tres nombres típicos de Kodi en .jpg antes de
# pasar a .png/.webp. Antes se probaban las 4 extensiones de "poster"
# antes de mirar "folder.jpg", gastando requests de más en cada carpeta.
POSTER_EXT_ORDER = [".jpg", ".png", ".webp", ".jpeg"]
POSTER_CANDIDATE_NAMES = ["poster", "folder", "cover"]

# El caché guarda las imágenes YA reducidas y en JPEG, no el original
# completo en PNG. Antes se guardaba el archivo tal como venía (a veces
# 2000x3000 o 3840x2160) re-encodeado como PNG: la caché llegó a ocupar
# más de 5 GB y cada carátula tardaba en leerse/decodificarse aunque en
# pantalla se muestre a 152x228. Con estos topes (pensados para pantallas
# Retina) alcanza de sobra y la carga es mucho más rápida.
POSTER_MAX_SIZE = (512, 768)     # tarjetas/detalle/grilla/álbum
BACKDROP_MAX_SIZE = (1600, 900)  # hero y fondos panorámicos
JPEG_QUALITY = 85

# Cuántas imágenes se mantienen en RAM para no releerlas del disco cada
# vez que el home se repinta o el usuario filtra/cambia de vista.
MEMORY_CACHE_MAX = 320
MISSING_TTL = 7 * 24 * 3600  # reintenta "sin carátula" después de una semana

_RESAMPLE = getattr(Image, "Resampling", Image).LANCZOS


def _is_jpeg(data: bytes) -> bool:
    return data.startswith(b"\xff\xd8\xff")


def _target_for_key(key: str) -> tuple[tuple[int, int], int]:
    """Tamaño máximo y calidad con los que cachear según el tipo de uso."""
    if key.endswith("#backdrop"):
        return BACKDROP_MAX_SIZE, JPEG_QUALITY
    return POSTER_MAX_SIZE, JPEG_QUALITY


def _strip_ext(name: str) -> str:
    if "." in name:
        return name.rsplit(".", 1)[0]
    return name


def candidate_urls_for(entry: Entry, siblings: list[Entry]) -> list[str]:
    """Devuelve URLs candidatas a carátula para una entrada, en orden de prioridad."""
    candidates: list[str] = []
    base = _strip_ext(entry.name).lower()

    # 1) hermano con mismo nombre base + extensión de imagen
    for sib in siblings:
        if sib.is_dir or sib.url == entry.url:
            continue
        if _strip_ext(sib.name).lower() == base and sib.ext in IMAGE_EXTS:
            candidates.append(sib.url)

    # 2) para carpetas, nombres típicos de Kodi dentro de la carpeta
    if entry.is_dir:
        folder_url = entry.url if entry.url.endswith("/") else entry.url + "/"
        for ext in POSTER_EXT_ORDER:
            for name in POSTER_CANDIDATE_NAMES:
                candidates.append(urljoin(folder_url, name + ext))

    return candidates


def in_folder_poster_candidates(entries: list[Entry]) -> list[str]:
    """Elige la mejor imagen para usar como póster DENTRO de una carpeta
    ya abierta (a diferencia de candidate_urls_for, que es para el caso
    de mostrar la carátula de una carpeta vista desde AFUERA)."""
    imgs = [e for e in entries if not e.is_dir and e.ext in IMAGE_EXTS]
    priority = [e for e in imgs if "poster" in e.name.lower()]
    priority += [e for e in imgs if "cover" in e.name.lower() and e not in priority]
    others = [e for e in imgs if e not in priority]
    return [e.url for e in (priority + others)]


def in_folder_backdrop_candidates(entries: list[Entry]) -> list[str]:
    """Imagen tipo fanart/backdrop (panorámica) dentro de la carpeta, si hay."""
    imgs = [e for e in entries if not e.is_dir and e.ext in IMAGE_EXTS]
    matches = [
        e for e in imgs
        if any(k in e.name.lower() for k in ("fanart", "backdrop", "background"))
    ]
    return [e.url for e in matches]


def _looks_like_real_image(data: bytes) -> bool:
    """Valida por los bytes reales del archivo (firma/"magic bytes"),
    no por lo que diga la extensión de la URL o el content-type del
    servidor. Esto es clave para las carátulas ADIVINADAS (poster.jpg,
    folder.jpg, etc.): si no existen de verdad, algunos servidores
    devuelven una página de error disfrazada de 200 OK, y pasarle esos
    bytes a QPixmap puede crashear feo en macOS (excepción nativa de
    Cocoa que ni siquiera Python puede atajar con try/except)."""
    if not data or len(data) < 12:
        return False
    if data.startswith(b"\xff\xd8\xff"):          # JPEG
        return True
    if data.startswith(b"\x89PNG\r\n\x1a\n"):      # PNG
        return True
    if data.startswith((b"GIF87a", b"GIF89a")):    # GIF
        return True
    if data[:2] == b"BM":                          # BMP
        return True
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":  # WEBP
        return True
    return False


def _revalidate_and_reencode(
    data: bytes,
    max_size: tuple[int, int] | None = None,
    quality: int = JPEG_QUALITY,
) -> bytes | None:
    """Segunda barrera, más fuerte que _looks_like_real_image: decodifica
    la imagen completa con Pillow, la reduce y la vuelve a guardar limpia
    como JPEG.

    ¿Por qué? _looks_like_real_image solo mira los primeros bytes (la
    "firma" del formato). Un archivo truncado a mitad de descarga, o
    corrupto de otra forma, puede tener una firma perfectamente válida
    y aun así crashear al decodificador nativo de imágenes de macOS con
    una excepción que ni Python puede atajar (aborta todo el proceso).
    Pillow, en cambio, lanza una excepción NORMAL de Python ante datos
    corruptos, así que la usamos como "cuarentena": si Pillow no puede
    abrir y decodificar la imagen entera sin errores, la descartamos
    acá y no llega nunca a Qt/macOS.

    Además de validar, acá aprovechamos para dejar la imagen en el
    tamaño en que realmente se usa (`max_size`) y en JPEG. Esto es lo
    que hace la diferencia en velocidad: no tiene sentido guardar una
    carátula de 3000 px de alto para mostrarla a 228 px.
    """
    try:
        img = Image.open(io.BytesIO(data))
        # En JPEG, `draft()` hace que el decodificador entregue una
        # versión reducida (1/2, 1/4, 1/8…) sin decodificar todos los
        # píxeles originales. Es mucho más rápido y, como igual vamos a
        # achicar, no se nota diferencia visual.
        if max_size and img.format == "JPEG":
            try:
                img.draft("RGB", max_size)
            except Exception:
                pass
        img.load()  # decodifica completo: detecta truncamientos/corrupción
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "LA") or "transparency" in img.info:
            # JPEG no tiene canal alfa: aplanamos sobre el fondo oscuro
            # de la app en vez de dejar halos negros.
            base = Image.new("RGB", img.size, (20, 22, 26))
            rgba = img.convert("RGBA")
            base.paste(rgba, mask=rgba.split()[-1])
            img = base
        else:
            img = img.convert("RGB")
        if max_size:
            img.thumbnail(max_size, _RESAMPLE)
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=quality)
        return out.getvalue()
    except Exception:
        return None


class ThumbnailManager(QObject):
    """Descarga carátulas en hilos de trabajo y notifica a la UI vía señal.

    La decodificación a QPixmap se hace en el hilo principal (el slot
    conectado a `thumbnail_ready`), porque QPixmap no es seguro de crear
    fuera del hilo de la GUI. Acá solo viajan bytes crudos.
    """

    thumbnail_ready = Signal(str, bytes)   # key (normalmente entry.url), datos de imagen
    thumbnail_missing = Signal(str)        # key sin carátula encontrada

    def __init__(self, session, cache_dir: Path, max_workers: int = 8):
        super().__init__()
        self.session = session
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._missing_path = cache_dir / "missing.json"
        # Dos colas: las imágenes que el usuario está mirando (ficha,
        # grilla, hero) no tienen que esperar detrás de las ~80 carátulas
        # del home que se piden al abrir la app.
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._priority_executor = ThreadPoolExecutor(max_workers=3)
        self._lock = threading.Lock()
        self._inflight: set[str] = set()
        # Caché en RAM (LRU acotada) para que repintar/filtrar el home no
        # vuelva a leer del disco ni a decodificar la misma imagen.
        self._memory: OrderedDict[str, bytes] = OrderedDict()
        # Claves sin carátula (persiste entre arranques) para no hacer
        # requests innecesarios en la siguiente carga.
        self._missing: dict[str, float] = {}
        self._load_missing()

    def request(self, key: str, candidates: list[str], priority: bool = False):
        cached = self._recall(key)
        if cached is not None:
            self.thumbnail_ready.emit(key, cached)
            return

        if self._is_missing(key):
            self.thumbnail_missing.emit(key)
            return

        with self._lock:
            if key in self._inflight:
                return
            if not candidates:
                submit = False
            else:
                self._inflight.add(key)
                submit = True

        if not submit:
            self._mark_missing(key)
            self.thumbnail_missing.emit(key)
            return
        executor = self._priority_executor if priority else self.executor
        try:
            executor.submit(self._fetch, key, candidates)
        except RuntimeError:
            # El executor ya se cerró (app cerrándose).
            with self._lock:
                self._inflight.discard(key)

    def shutdown(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
        self._priority_executor.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            self._memory.clear()
        self._save_missing()

    # --- caché en memoria ------------------------------------------------
    def _recall(self, key: str) -> bytes | None:
        with self._lock:
            data = self._memory.get(key)
            if data is not None:
                self._memory.move_to_end(key)
            return data

    def _remember(self, key: str, data: bytes):
        with self._lock:
            self._memory[key] = data
            self._memory.move_to_end(key)
            while len(self._memory) > MEMORY_CACHE_MAX:
                self._memory.popitem(last=False)

    def _load_missing(self):
        try:
            if not self._missing_path.exists():
                return
            data = json.loads(self._missing_path.read_text())
            now = time.time()
            if isinstance(data, dict):
                for key, ts in data.items():
                    try:
                        ts = float(ts)
                    except (TypeError, ValueError):
                        continue
                    if now - ts < MISSING_TTL:
                        self._missing[key] = ts
            elif isinstance(data, list):  # formato viejo (sin fecha)
                for key in data:
                    self._missing[key] = now
        except Exception:
            self._missing = {}

    def _is_missing(self, key: str) -> bool:
        with self._lock:
            ts = self._missing.get(key)
            if ts is None:
                return False
            if time.time() - ts >= MISSING_TTL:
                self._missing.pop(key, None)
                return False
            return True

    def _save_missing(self):
        try:
            now = time.time()
            # Copia bajo lock: varios workers pueden marcar claves a la vez.
            with self._lock:
                snapshot = list(self._missing.items())
            # Acotar y descartar vencidas para no crecer sin control.
            items = sorted(
                ((k, ts) for k, ts in snapshot if now - ts < MISSING_TTL),
                key=lambda item: item[1],
            )[-5000:]
            self._missing_path.write_text(json.dumps(dict(items)))
        except Exception:
            pass

    def _mark_missing(self, key: str):
        with self._lock:
            self._missing[key] = time.time()

    # --- caché en disco --------------------------------------------------
    def _cache_path(self, key: str) -> Path:
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.img"

    def _read_cache(self, key: str) -> bytes | None:
        cache_path = self._cache_path(key)
        try:
            if cache_path.exists() and cache_path.stat().st_size > 0:
                cached = cache_path.read_bytes()
                if _looks_like_real_image(cached):
                    return cached
                cache_path.unlink()
        except OSError:
            pass
        return None

    def _optimize_cached(self, key: str, cache_path: Path, data: bytes) -> bytes:
        """Migra entradas viejas del caché (PNG a tamaño original) a JPEG
        reducido. Ocurre una sola vez por imagen y en un hilo de trabajo,
        así no hay que borrar la caché ni volver a descargar todo."""
        if _is_jpeg(data):
            return data
        max_size, quality = _target_for_key(key)
        optimized = _revalidate_and_reencode(data, max_size, quality)
        if optimized is None:
            return data  # no pudimos mejorarla, pero sigue siendo usable
        try:
            cache_path.write_bytes(optimized)
        except OSError:
            pass
        return optimized

    def _fetch(self, key: str, candidates: list[str]):
        try:
            cache_path = self._cache_path(key)
            cached = self._read_cache(key)
            if cached is not None:
                cached = self._optimize_cached(key, cache_path, cached)
                self._remember(key, cached)
                self.thumbnail_ready.emit(key, cached)
                return

            max_size, quality = _target_for_key(key)
            for url in candidates:
                try:
                    resp = self.session.get(url, timeout=8)
                except Exception:
                    continue
                if resp.status_code != 200 or not resp.content:
                    continue
                if not _looks_like_real_image(resp.content):
                    continue  # no es una imagen real (probablemente 404 disfrazado)
                safe_data = _revalidate_and_reencode(resp.content, max_size, quality)
                if safe_data is None:
                    continue  # firma válida pero imagen corrupta/truncada: probamos el siguiente candidato
                try:
                    cache_path.write_bytes(safe_data)
                except Exception:
                    pass
                self._remember(key, safe_data)
                self.thumbnail_ready.emit(key, safe_data)
                return

            self._mark_missing_final(key)
        finally:
            with self._lock:
                self._inflight.discard(key)

    def _mark_missing_final(self, key: str):
        self._mark_missing(key)
        self._save_missing()
        self.thumbnail_missing.emit(key)
