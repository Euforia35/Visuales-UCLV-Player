"""
naming.py
----------
Utilidades para convertir nombres de archivo/carpeta crudos (del listado
de Apache) en títulos legibles estilo catálogo: "Interestelar.2014.1080p.BluRay.x264"
→ "Interestelar (2014)", "Breaking.Bad.S01E05.720p.mkv" → "T1 · E5 ...".
"""

from __future__ import annotations

import re
from urllib.parse import unquote

# Tokens típicos de releases que NO son parte del título. Se comparan
# token a token (separados por puntos/guiones/espacios), así no comemos
# palabras legítimas que contengan partes de estos patrones.
_NOISE_TOKEN_RE = re.compile(
    r"""^(
        \d{3,4}p | 4k | uhd | hd | fhd |
        web-?dl | webrip | web | hdtv | dvdrip? | dvd | bluray | blu-?ray | blu | ray |
        bdrip | brrip | remux | hdr | sdr | dv | hdr10 | dolby | vision |
        x26[45] | h\.?26[45] | h\.?266 | hevc | avc | xvid | divx | 10bit | 8bit |
        dsnp | atvp | amzn | nf | hmax | max | pcok | cbs | abc | hulu | itunes |
        aac\d* | ac3 | eac3 | ddp?\d* | dts(?:-?hd)? | truehd | atmos |
        flac\d* | opus | mp3 |
        esp(?:anol)? | lat(?:ino)? | castellano | sub(?:titulado|s)? | dubs? |
        complete | proper | reprisal | limited | uncensored | multi |
        \d+(?:\.\d+)?[kmg]b? |
        s\d{1,2}e\d{1,3} | s\d{1,2} | e\d{1,3} | t\d{1,2} |
        temporada\d+ | episodio\d+ | capitulo\d+ | cap\d+ | ep\d+ |
        cd\d | dvd\d | parte\d+ | vol(?:umen)?\.?\d+
    )$""",
    re.IGNORECASE | re.VERBOSE,
)

_YEAR_RE = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_VIDEO_EXT_RE = re.compile(r"\.[A-Za-z0-9]{2,4}$")

_EPISODE_PATTERNS = [
    re.compile(r"\bs(\d{1,2})[\s._-]*e(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})x(\d{1,3})\b"),
    re.compile(r"\bep?(?:isodio)?[\s._-]*(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\bcap(?:itulo)?[\s._-]*(\d{1,3})\b", re.IGNORECASE),
]

# Marcador de episodio unificado (para partir título antes/después)
_MARKER_RE = re.compile(
    r"\bs\d{1,2}[\s._-]*e\d{1,3}\b"
    r"|\b\d{1,2}x\d{1,3}\b"
    r"|\b(?:ep|episodio|cap|capitulo)[\s._-]*\d{1,3}\b",
    re.IGNORECASE,
)


def parse_year(name: str) -> str | None:
    """Primer año (1900-2099) que aparezca como token suelto en el nombre."""
    m = _YEAR_RE.search(unquote(name))
    return m.group(1) if m else None


def clean_display_title(name: str) -> str:
    """Nombre crudo de carpeta/archivo -> título legible para la UI.

    - quita la extensión de video (si la hay)
    - saca tokens de release (1080p, BluRay, x264-GROUP…) y colas de
      audio pegadas ("DDP5.1")
    - deja el año al final entre paréntesis, estilo catálogo
    """
    raw = unquote(name or "").strip()
    if not raw:
        return ""
    base = raw
    # Si termina en una extensión que NO es un año, la quitamos.
    m = re.search(r"\.([A-Za-z0-9]{2,4})$", base)
    if m and not re.fullmatch(r"(19|20)\d{2}", m.group(1)):
        base = base[: m.start()]

    # Colas de audio/códec con dígitos pegados ("DDP5.1", "AC3-EAC3",
    # "DD5.1.x264"): se van enteras antes del filtro token a token, para
    # no dejar números sueltos ("... Home 1 (2021)").
    base = re.sub(
        r"\b(ddp?|e?ac3|dts(?:-hd)?|truehd|atmos|aac|flac|opus|mp3)"
        r"(?:[.\s_-]*(ma|hd|x|plus))?[\d.\s_-]*\d*(?:[.\s_-]\d+)*",
        " ",
        base,
        flags=re.IGNORECASE,
    )

    year = parse_year(base)
    if year:
        base = _YEAR_RE.sub(" ", base)

    # Normaliza a tokens separados por espacio. El guión también separa
    # ("x264-GROUP" -> "x264" "GROUP"), pero recordamos la posición de
    # esos cortes para saber qué token es "cola de release": si el token
    # anterior era ruido de release y venía pegado con guión, este token
    # también se descarta (nombre del grupo, "DL", "HD", etc.).
    pieces = re.split(r"[.\s_]+", base)
    tokens: list[str] = []
    glued = []  # True si el token vino de partir un guión sin espacios
    for piece in pieces:
        sub = re.split(r"[-–]", piece)
        for i, part in enumerate(sub):
            if part:
                tokens.append(part)
                glued.append(i > 0)
    kept: list[str] = []
    for i, token in enumerate(tokens):
        core = token.strip("-()[]")
        if _NOISE_TOKEN_RE.match(core):
            continue
        if glued[i] and kept and i > 0 and _NOISE_TOKEN_RE.match(tokens[i - 1].strip("-()[]")):
            continue  # cola pegada a un token de release ("-GROUP")
        # "x264-GROUP": si el token ANTERIOR era códec y este vino pegado
        # por guión, es el grupo de release
        if glued[i] and i > 0 and re.match(r"^x26[45]$|^h\.?26[45]$", tokens[i - 1], re.IGNORECASE):
            continue
        kept.append(token)
    title = " ".join(kept).strip(" -–[]()·,")
    title = " ".join(title.split())

    if not title:
        title = " ".join(tokens) or raw
    if year:
        title = f"{title} ({year})"
    return title


def episode_label(name: str) -> str | None:
    """"T1 · E5" si el nombre codifica temporada/episodio, si no None."""
    text = unquote(name)
    for pattern in _EPISODE_PATTERNS:
        m = pattern.search(text)
        if m:
            groups = m.groups()
            if len(groups) == 2:
                season, ep = int(groups[0]), int(groups[1])
                return f"T{season} · E{ep}"
            return f"E{int(groups[0]):02d}"
    return None


def episode_display(name: str) -> str:
    """Nombre de video en una carpeta de serie -> texto de botón:
    "T1 · E5  ·  Some Title" (sin extensión ni tokens de release).

    El título puede venir ANTES del marcador ("Serie.S01E05.mkv") o
    DESPUÉS ("1x03 - El título.mkv"); se usa el lado que tenga texto.
    """
    raw = unquote(name or "").strip()
    label = episode_label(raw)

    before = raw
    after = ""
    m = _MARKER_RE.search(raw)
    if m:
        before = raw[: m.start()]
        after = raw[m.end():]

    LOGO_RE = r"^(ep|episodio|cap|capitulo|parte|s\d+e\d+|\d+x\d+)[\s._-]*\d*\b.*$"
    title_before = clean_display_title(before) if before.strip() else ""
    after_clean = _VIDEO_EXT_RE.sub("", after).strip(" -–._[]()·,")
    title_after = clean_display_title(after_clean) if after_clean else ""
    # descarta un "título" que en realidad es el marcador repetido
    if title_after and re.match(LOGO_RE, title_after, re.IGNORECASE):
        title_after = ""
    if title_before and re.match(LOGO_RE, title_before, re.IGNORECASE):
        title_before = ""

    title = title_before or title_after
    if not title:
        title = clean_display_title(raw)
    if label and title:
        return f"{label}  ·  {title}"
    return label or title or raw


def format_runtime(minutes: float | None) -> str:
    """"1 h 49 min" / "48 min" a partir de minutos."""
    if not minutes or minutes <= 0:
        return ""
    minutes = int(minutes)
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} h {m} min"
    if h:
        return f"{h} h"
    return f"{m} min"
