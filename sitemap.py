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

import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, unquote, quote

from bs4 import BeautifulSoup

from naming import clean_display_title

SITEMAP_NAME = "listado.html"
# El árbol cambia poco; lo refrescamos cada tanto (7 días).
STALE_AFTER_SECONDS = 7 * 24 * 3600


@dataclass
class SiteEntry:
    """Resultado de búsqueda dentro del árbol de carpetas."""

    name: str
    url: str
    parent_path: str
    is_dir: bool = True


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
        self._rebuild_children()
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
        self._rebuild_children()
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

    def _rebuild_children(self):
        """Índice padre → hijos directos (una sola pasada por las
        ~30.000 rutas, en vez de filtrar todo el set en cada consulta)."""
        self._children.clear()
        for path in self.paths:
            parent = path.rsplit("/", 1)[0]
            self._children.setdefault(parent, []).append(path)
        for kids in self._children.values():
            kids.sort()

    def children(self, path: str) -> list[str]:
        """Rutas hijas directas de `path`."""
        path = path.rstrip("/")
        if not self._children and self.paths:
            self._rebuild_children()
        return self._children.get(path, [])

    def leaf_children(self, path: str) -> list[str]:
        """Hijos directos que son hojas (sin subcarpetas): candidatos a
        películas/series individuales."""
        return [c for c in self.children(path) if not self.children(c)]

    def content_folders(self, root: str, limit: int = 30) -> list[str]:
        """Carpetas \"de contenido\" dentro de `root`, repartiendo el
        cupo entre las subcategorías de primer nivel.

        Antes se hacía un BFS que se llenaba con la primera carpeta
        grande (Peliculas/Cubanas, Series/Espanol…), así que las filas
        del home mostraban siempre lo mismo. Ahora se toma una cuota de
        cada grupo y, dentro de los grupos por año (Extranjeras/2024,
        2025…), se empieza por los años más recientes."""
        root = root.rstrip("/")
        groups = [c for c in self.children(root) if self.children(c)]
        if not groups:
            return self.leaf_children(root)[:limit]

        # Cuota por grupo (si un grupo no llega a la cuota, el resto se
        # completa con los demás al final).
        per_group = max(1, limit // len(groups))
        results: list[str] = []
        for group in groups:
            results.extend(self._leaves_under(group, per_group))
            if len(results) >= limit:
                break

        if len(results) < limit:
            for group in groups:
                for leaf in self._leaves_under(group, per_group * 2):
                    if leaf not in results:
                        results.append(leaf)
                        if len(results) >= limit:
                            break
                if len(results) >= limit:
                    break
        return results[:limit]

    def _leaves_under(self, path: str, limit: int) -> list[str]:
        """Hojas debajo de `path` (BFS acotado). Si `path` contiene
        subcarpetas con nombre de año (1900s, 2024…), las recorre de la
        más nueva a la más vieja."""
        results: list[str] = []
        queue = [path]
        visited = {path}
        while queue and len(results) < limit:
            current = queue.pop(0)
            kids = self.children(current)
            if not kids:
                results.append(current)
                continue
            for kid in self._sort_kids(kids):
                if kid not in visited:
                    visited.add(kid)
                    queue.append(kid)
        return results

    @staticmethod
    def _year_group_value(name: str) -> int | None:
        """1900s → 1900, 2024 → 2024, 18xxs → 1800; None si no es año."""
        m = re.fullmatch(r"((?:18|19|20)\d{2})s?", name)
        if m:
            return int(m.group(1))
        m = re.fullmatch(r"(\d{2})xxs", name)
        if m:
            return int(m.group(1)) * 100
        return None

    @classmethod
    def _sort_kids(cls, kids: list[str]) -> list[str]:
        """Ordena hijos dejando primero los años/décadas más recientes."""
        # Solo cambiamos el orden si TODOS los hijos parecen años;
        # en una lista de series alfabética no queremos invertir nada.
        if kids and all(
            cls._year_group_value(k.rsplit("/", 1)[-1]) is not None for k in kids
        ):
            return sorted(
                kids,
                key=lambda p: (
                    -cls._year_group_value(p.rsplit("/", 1)[-1]),
                    p,
                ),
            )
        return sorted(kids)

    # ------------------------------------------------------------------
    # Búsqueda por título en el árbol cacheado
    # ------------------------------------------------------------------
    def search(self, query: str, limit: int = 120) -> list[SiteEntry]:
        """Busca por nombre de carpeta en TODO el sitio, usando el
        índice de `listado.html` (sin recorrer carpetas por red)."""
        query = query.strip().casefold()
        if not query:
            return []
        hits: list[tuple[tuple, str, str]] = []
        for path in self.paths:
            raw_name = path.rsplit("/", 1)[-1]
            name = unquote(raw_name)
            if query not in name.casefold():
                continue
            is_leaf = not self.children(path)
            exact_start = 0 if name.casefold().startswith(query) else 1
            # Carpetas de contenido (hojas) primero; los agrupadores
            # ("Cubanas", "Extranjeras", "Ingles") quedan después.
            score = (exact_start, 0 if is_leaf else 1, len(name), name.casefold())
            hits.append((score, path, name))
        hits.sort(key=lambda h: h[0])

        results: list[SiteEntry] = []
        for _score, path, name in hits[:limit]:
            parent = path.rsplit("/", 1)[0]
            parent_label = "Inicio" + "".join(
                f"  ›  {unquote(part)}" for part in parent.split("/") if part
            )
            results.append(SiteEntry(
                name=clean_display_title(name) or name,
                url=self.base_url + quote(path.lstrip("/"), safe="/") + "/",
                parent_path=parent_label,
            ))
        return results
