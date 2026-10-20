"""
tmdb.py
-------
Busca metadatos de una película/serie en The Movie Database (TMDb) vía
su API REST gratuita: sinopsis en español, póster, backdrop panorámico,
año, duración, géneros y rating.

Requiere una API Key gratuita e instantánea: registrate en
https://www.themoviedb.org/settings/api (elegí "Developer" — es gratis
para uso personal/no comercial).

A diferencia de OMDb (que solo devuelve el texto tal cual está en IMDb,
casi siempre en inglés), TMDb sí permite pedir la sinopsis en un idioma
específico (acá pedimos "es-ES") cuando existe esa traducción cargada
— que es el caso de la gran mayoría de películas conocidas.
"""

from __future__ import annotations

import requests

API_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p/w500"
BACKDROP_BASE = "https://image.tmdb.org/t/p/w1280"

# Mapa estático de ids de género -> nombre (en español). Evita un request
# extra a /genre/... por cada búsqueda; los ids de TMDb son estables.
GENRE_NAMES = {
    28: "Acción", 12: "Aventura", 16: "Animación", 35: "Comedia",
    80: "Crimen", 99: "Documental", 18: "Drama", 10751: "Familia",
    14: "Fantasía", 36: "Historia", 27: "Terror", 10402: "Música",
    9648: "Misterio", 10749: "Romance", 878: "Ciencia ficción",
    10770: "Película de TV", 53: "Suspense", 10752: "Bélica",
    37: "Western",
    10759: "Acción y aventura", 10762: "Infantil", 10763: "Noticias",
    10764: "Reality", 10765: "Ciencia ficción y fantasía",
    10766: "Soap", 10767: "Talk", 10768: "Guerra y política",
}


def fetch_media_info(
    api_key: str,
    title: str,
    year: str | None = None,
    language: str = "es-ES",
    media_type: str = "movie",
    timeout: float = 10.0,
) -> tuple[dict, str]:
    """Devuelve (info, error). info (si no hay error):

        title, year, runtime_min, genres (list[str]), rating (float),
        overview, poster_url, backdrop_url, media_type

    media_type: "movie" o "tv" (series) — usan endpoints y nombres de
    parámetro de año distintos en la API de TMDb.
    """
    if not api_key:
        return {}, "Falta la API Key de TMDb."
    if not title.strip():
        return {}, "Falta un título para buscar."
    if media_type not in ("movie", "tv"):
        media_type = "movie"

    year_param = "first_air_date_year" if media_type == "tv" else "year"
    params = {"api_key": api_key, "query": title, "language": language}
    if year:
        params[year_param] = year

    try:
        resp = requests.get(f"{API_BASE}/search/{media_type}", params=params, timeout=timeout)
        if resp.status_code == 401:
            return {}, "API Key de TMDb inválida."
        resp.raise_for_status()
        results = (resp.json().get("results")) or []
        if not results:
            tipo = "serie" if media_type == "tv" else "película"
            return {}, f'No se encontró "{title}" ({tipo}) en TMDb.'

        best = results[0]
        overview = (best.get("overview") or "").strip()
        fallback_note = ""

        if not overview and language != "en-US":
            # Esta ficha todavía no tiene sinopsis cargada en español —
            # probamos en inglés antes de rendirnos, mejor eso que nada.
            params["language"] = "en-US"
            resp2 = requests.get(f"{API_BASE}/search/{media_type}", params=params, timeout=timeout)
            resp2.raise_for_status()
            results2 = (resp2.json().get("results")) or []
            if results2:
                overview = (results2[0].get("overview") or "").strip()
                if overview:
                    fallback_note = "\n\n(No había sinopsis en español para este título — esta está en inglés.)"

        date = best.get("release_date") or best.get("first_air_date") or ""
        year_val = date[:4] if len(date) >= 4 else (year or "")

        runtime_min = 0
        if media_type == "tv":
            ert = best.get("episode_run_time") or []
            if ert:
                runtime_min = int(ert[0])
        else:
            runtime_min = int(best.get("runtime") or 0)

        genres = [
            GENRE_NAMES.get(gid, "")
            for gid in (best.get("genre_ids") or [])
        ]
        genres = [g for g in genres if g]

        poster_path = best.get("poster_path") or ""
        backdrop_path = best.get("backdrop_path") or ""

        info = {
            "title": (best.get("title") or best.get("name") or title).strip(),
            "year": year_val,
            "runtime_min": runtime_min,
            "genres": genres,
            "rating": float(best.get("vote_average") or 0),
            "overview": overview + fallback_note,
            "poster_url": f"{IMAGE_BASE}{poster_path}" if poster_path else "",
            "backdrop_url": f"{BACKDROP_BASE}{backdrop_path}" if backdrop_path else "",
            "media_type": media_type,
        }
        return info, ""
    except requests.RequestException as exc:
        return {}, f"No se pudo conectar con TMDb: {exc}"
    except Exception as exc:
        return {}, f"Error al buscar en TMDb: {exc}"


def fetch_synopsis(
    api_key: str,
    title: str,
    year: str | None = None,
    language: str = "es-ES",
    media_type: str = "movie",
    timeout: float = 10.0,
) -> tuple[str, str, str]:
    """Compatibilidad con el uso viejo: devuelve (sinopsis, url_poster, error)."""
    info, error = fetch_media_info(api_key, title, year, language, media_type, timeout)
    if error:
        return "", "", error
    if not info.get("overview"):
        return "", info.get("poster_url", ""), f'"{title}" está en TMDb pero no tiene sinopsis cargada.'
    return info["overview"], info.get("poster_url", ""), ""
