"""
sitemap.py
----------
El servidor de visuales.uclv.cu publica en su raíz un archivo
`listado.html` (generado con la herramienta `tree`) que contiene el
ÁRBOL COMPLETO de carpetas del sitio en una sola descarga (~4.5 MB,
unas 30.000 carpetas).

Eso es mucho mejor que escanear el sitio carpeta por carpeta: un solo
request nos da el esqueleto entero, que después se cachea en disco.

Este módulo:
  - descarga y parsea ese árbol (solo carpetas; no incluye archivos),
  - lo guarda en caché (una lista de rutas normalizadas),
  - ofrece consultas rápidas: hijos de una carpeta, si es hoja, etc.

El home (main_window.py) lo usa para llenar las filas de contenido sin
tener que recorrer el servidor.
"""

from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import urlparse, unquote

from bs4 import BeautifulSoup

SITEMAP_NAME = "listado.html"
# El árbol cambia poco; lo refrescamos cada tanto (7 días).
STALE_AFTER_SECONDS = 7 * 24 * 3600


class SiteMap:
    """Árbol de carpetas del sitio, cargado de `listado.html`."""

    def __init__(self, base_url: str, cache_path: Path, session=None):
        self.base_url = base_url.rstrip("/") + "/"
        self.cache_path = cache_path
        self.session = session
        self.paths: set[str] = set()   # rutas normalizadas, sin barra final
        self.built_at: float = 0.0
        self._children: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------
    def load_from_disk(self) -> bool:
        if not self.cache_path.exists():
            return False
        try:
            import json
            data = json.loads(self.cache_path.read_text())
        except Exception:
            return False
        self.built_at = data.get("built_at", 0.0)
        self.paths = set(data.get("paths", []))
        self._children.clear()
        return bool(self.paths)

    def is_stale(self) -> bool:
        return (time.time() - self.built_at) > STALE_AFTER_SECONDS

    def _save_to_disk(self):
        import json
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps({
                "built_at": self.built_at,
                "paths": sorted(self.paths),
            }))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Descarga / parseo
    # ------------------------------------------------------------------
    def fetch(self) -> bool:
        """Descarga y parsea `listado.html`. Devuelve True si consiguió
        algo. No lanza: deja self.paths vacío si falla."""
        if self.session is None:
            return False
        url = self.base_url + SITEMAP_NAME
        try:
            resp = self.session.get(url, timeout=(15, 90))
            resp.raise_for_status()
        except Exception:
            return False
        paths = self._parse(resp.text)
        if not paths:
            return False
        self.paths = paths
        self._children.clear()
        self.built_at = time.time()
        self._save_to_disk()
        return True

    @staticmethod
    def _parse(html: str) -> set[str]:
        soup = BeautifulSoup(html, "html.parser")
        out: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "visuales.uclv.cu" not in href:
                continue
            path = unquote(urlparse(href).path)
            # el árbol usa doble barra inicial ("//Peliculas/...")
            path = path.replace("//", "/")
            if path.endswith("/") and path != "/":
                out.add(path.rstrip("/"))
        return out

    # ------------------------------------------------------------------
    # Consultas
    # ------------------------------------------------------------------
    def ensure_loaded(self) -> bool:
        """Carga de disco si hace falta; si está viejo o falta, descarga."""
        if not self.paths and not self.load_from_disk():
            return self.fetch()
        if self.is_stale():
            # refresca en segundo plano sin bloquear si falla
            self.fetch()
        return bool(self.paths)

    def children(self, path: str) -> list[str]:
        """Rutas hijas directas de `path`."""
        path = path.rstrip("/")
        if path in self._children:
            return self._children[path]
        depth = path.count("/")
        kids = [p for p in self.paths
                if p.startswith(path + "/") and p.count("/") == depth + 1]
        kids.sort()
        self._children[path] = kids
        return kids

    def leaf_children(self, path: str) -> list[str]:
        """Hijos directos que son hojas (sin subcarpetas): candidatos a
        películas/series individuales."""
        return [c for c in self.children(path) if not self.children(c)]

    def content_folders(self, root: str, limit: int = 30) -> list[str]:
        """Carpetas \"de contenido\" dentro de `root`, bajando por los
        niveles que solo agrupan (sus hijos no son hojas) hasta dar con
        carpetas que sí contienen elementos individuales.

        Devuelve rutas completas, en orden estable."""
        root = root.rstrip("/")
        results: list[str] = []
        # BFS acotado: primero lo más cercano a la raíz
        queue = [root]
        visited = {root}
        while queue and len(results) < limit:
            current = queue.pop(0)
            kids = self.children(current)
            if not kids:
                continue
            leaves = [c for c in kids if not self.children(c)]
            # Si la mayoría de los hijos son hojas, ESTE nivel ya es
            # el de contenido (sus hijos son las películas/series).
            if len(leaves) >= max(3, len(kids) // 2):
                results.extend(leaves)
                continue
            # Si no, es un nivel de agrupación: bajamos por los hijos.
            for c in kids:
                if c not in visited:
                    visited.add(c)
                    queue.append(c)
        return results[:limit]
