"""
theme.py
--------
Tokens de diseño (colores, tamaños) + generador del stylesheet QSS.

Todo el color de la app vive acá: antes los hex estaban duplicados en
style.qss y en ~6 archivos Python. Si querés iterar el tema, cambia los
valores de abajo y la QSS se regenera sola al arrancar (no hace falta
mantener style.qss a mano).
"""

from __future__ import annotations

from string import Template

# --- Tokens de color ----------------------------------------------------
ACCENT = "#E63946"            # rojo principal (botones, selección, progreso)
ACCENT_HOVER = "#F04452"      # acento aclarado para hover
ACCENT_SOFT = "#5A2229"       # acento muy oscuro (fondos sutiles)

BG = "#14161A"                # fondo principal
SIDEBAR_BG = "#0D0F12"        # fondo del sidebar / barras inferiores
SIDEBAR_BORDER = "#22252B"
SURFACE = "#1E2127"           # superficies (botones, inputs, placeholders)
SURFACE_ALT = "#242830"       # superficie alternada (archivos no-video)
SURFACE_HOVER = "#2A2E36"
BORDER = "#2A2E36"
BORDER_HOVER = "#3A3F49"

TEXT = "#E8E8E8"
TEXT_STRONG = "#FFFFFF"
TEXT_SYNOPSIS = "#D5D8DD"
TEXT_BREADCRUMB = "#B7BBC2"
TEXT_DIM = "#9A9FA8"
TEXT_MUTED = "#8A8F98"
TEXT_FAINT = "#6E7280"
GLYPH_DIM = "#4A4F59"

RATING = "#FFC94D"            # amarillo para estrellas de rating

# --- Tamaños ------------------------------------------------------------
POSTER_RADIUS = 10            # radio de esquinas de pósters
CARD_RADIUS = 16             # radio del borde de hover de las tarjetas

_QSS = Template("""

* {
    font-family: ".AppleSystemUIFont", "Helvetica Neue", sans-serif;
    color: $TEXT;
}

QMainWindow, QWidget {
    background-color: $BG;
}

/* Los QLabel no pintan fondo: sobre el hero/backdrop deben dejar ver la
   imagen (si no, cada texto tapa el banner con un rectángulo oscuro). */
QLabel {
    background-color: transparent;
}

#topbar {
    background-color: $SIDEBAR_BG;
    border-bottom: 1px solid $SIDEBAR_BORDER;
}

#logo {
    font-size: 18px;
    font-weight: 700;
    color: $ACCENT;
    letter-spacing: 1px;
}

#exploreBtn {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 7px 12px;
    font-size: 13px;
    font-weight: 600;
    color: $TEXT;
}

#exploreBtn:hover {
    background-color: $SURFACE;
}

#exploreBtn::menu-indicator {
    image: none;
    width: 0px;
}

#iconBtn {
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 15px;
    color: $TEXT;
}

#iconBtn:hover {
    background-color: $SURFACE;
    border-color: $BORDER;
}

#iconBtn::menu-indicator {
    image: none;
    width: 0px;
}

#sectionLabel {
    font-size: 11px;
    font-weight: 600;
    color: $TEXT_MUTED;
    letter-spacing: 1px;
}

#rowTitle {
    font-size: 17px;
    font-weight: 700;
    color: $TEXT_STRONG;
}

#heroTitle {
    font-size: 30px;
    font-weight: 700;
    color: $TEXT_STRONG;
}

#heroSynopsis {
    font-size: 13px;
    color: $TEXT_SYNOPSIS;
}

#heroMeta {
    font-size: 12px;
    color: $TEXT_DIM;
}

QPushButton {
    background-color: $SURFACE;
    border: 1px solid $BORDER;
    border-radius: 8px;
    padding: 8px 12px;
    text-align: left;
    font-size: 13px;
}

QPushButton:hover {
    background-color: $SURFACE_HOVER;
}

QPushButton:pressed {
    background-color: $ACCENT;
    border-color: $ACCENT;
}

QToolButton {
    background-color: $SURFACE;
    border: 1px solid $BORDER;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: 14px;
}

QToolButton:hover {
    background-color: $SURFACE_HOVER;
}

#rowArrow {
    background-color: $SIDEBAR_BG;
    border: 1px solid $BORDER;
    border-radius: 14px;
    font-size: 14px;
    color: $TEXT;
}

#rowArrow:hover {
    background-color: $SURFACE_HOVER;
    border-color: $BORDER_HOVER;
}

#breadcrumb {
    font-size: 13px;
    color: $TEXT_BREADCRUMB;
}

#statusLabel {
    font-size: 11px;
    color: $TEXT_FAINT;
}

QLineEdit {
    background-color: $SURFACE;
    border: 1px solid $BORDER;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 13px;
}

QLineEdit:focus {
    border-color: $ACCENT;
}

QListWidget {
    background-color: transparent;
    border: none;
    font-size: 14px;
    outline: none;
}

QListWidget::item {
    padding: 9px 10px;
    border-radius: 6px;
}

QListWidget::item:hover {
    background-color: $SURFACE;
}

QListWidget::item:selected {
    background-color: $ACCENT;
    color: #FFFFFF;
}

#favList::item {
    font-size: 12px;
}

/* --- Menús desplegables (Explorar, Favoritos, Descargas) --------------- */
QMenu {
    background-color: $SURFACE;
    border: 1px solid $BORDER;
    border-radius: 8px;
    padding: 6px;
}

QMenu::item {
    background-color: transparent;
    padding: 8px 24px 8px 14px;
    border-radius: 6px;
    font-size: 13px;
    color: $TEXT;
}

QMenu::item:selected {
    background-color: $ACCENT;
    color: #FFFFFF;
}

QMenu::item:disabled {
    color: $TEXT_FAINT;
}

QMenu::separator {
    height: 1px;
    background: $BORDER;
    margin: 5px 8px;
}

QMenu::right-arrow {
    width: 0;
    height: 0;
}

QScrollBar:vertical {
    background: transparent;
    width: 10px;
}

QScrollBar::handle:vertical {
    background: $BORDER;
    border-radius: 5px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background: $BORDER_HOVER;
}

QScrollBar:horizontal {
    background: transparent;
    height: 10px;
}

QScrollBar::handle:horizontal {
    background: $BORDER;
    border-radius: 5px;
    min-width: 24px;
}

QScrollBar::handle:horizontal:hover {
    background: $BORDER_HOVER;
}

QScrollBar::up-arrow, QScrollBar::down-arrow,
QScrollBar::left-arrow, QScrollBar::right-arrow {
    width: 0;
    height: 0;
}

QListWidget[viewMode="1"]::item {
    padding: 6px;
    text-align: center;
}

#downloadsList {
    font-size: 11px;
}

#downloadsList::item {
    padding: 6px 4px;
    border-radius: 6px;
    margin-bottom: 2px;
}

#downloadsList::item:hover {
    background-color: $SURFACE;
}

#detailTitle {
    font-size: 28px;
    font-weight: 700;
    color: $TEXT_STRONG;
}

#detailMeta {
    font-size: 12px;
    color: $TEXT_DIM;
}

#detailSynopsis {
    font-size: 14px;
    color: $TEXT_SYNOPSIS;
    line-height: 1.5;
}

#playHeroBtn {
    background-color: $ACCENT;
    border: none;
    border-radius: 8px;
    padding: 12px 20px;
    font-size: 15px;
    font-weight: 600;
    color: #FFFFFF;
    text-align: center;
}

#playHeroBtn:hover {
    background-color: $ACCENT_HOVER;
}

#ghostBtn {
    background-color: rgba(255, 255, 255, 0.14);
    border: none;
    border-radius: 8px;
    padding: 12px 20px;
    font-size: 15px;
    font-weight: 600;
    color: $TEXT_STRONG;
    text-align: center;
}

#ghostBtn:hover {
    background-color: rgba(255, 255, 255, 0.24);
}

#chip {
    background-color: rgba(255, 255, 255, 0.10);
    border: 1px solid rgba(255, 255, 255, 0.10);
    border-radius: 12px;
    padding: 3px 10px;
    font-size: 12px;
    color: $TEXT_SYNOPSIS;
}

#chipRating {
    background-color: rgba(255, 201, 77, 0.14);
    border: 1px solid rgba(255, 201, 77, 0.35);
    border-radius: 12px;
    padding: 3px 10px;
    font-size: 12px;
    font-weight: 600;
    color: $RATING;
}

#mediaCard {
    background-color: transparent;
    border: 2px solid transparent;
    border-radius: ${CARD_RADIUS}px;
}

#mediaCard[hover="true"] {
    background-color: rgba(255, 255, 255, 0.06);
    border: 2px solid $ACCENT;
}

#cardTitle {
    font-size: 13px;
    font-weight: 600;
    color: $TEXT;
}

#cardMeta {
    font-size: 11px;
    color: $TEXT_DIM;
}

#episodeBtn {
    background-color: $SURFACE;
    border: 1px solid $BORDER;
    border-radius: 8px;
    padding: 10px 14px;
    text-align: left;
    font-size: 13px;
}

#episodeBtn:hover {
    background-color: $SURFACE_HOVER;
    border-color: $BORDER_HOVER;
}

#filesBtn {
    background-color: transparent;
    border: 1px solid $BORDER;
    border-radius: 8px;
    padding: 8px 14px;
    font-size: 13px;
    color: $TEXT_DIM;
    text-align: center;
}

#filesBtn:hover {
    background-color: $SURFACE;
    color: $TEXT;
}

#heroEmpty {
    font-size: 13px;
    color: $TEXT_FAINT;
}

#homeLoading {
    font-size: 14px;
    color: $TEXT_FAINT;
}

#musicBar {
    background-color: $SIDEBAR_BG;
    border-top: 1px solid $SIDEBAR_BORDER;
}

#playerControls {
    background-color: $SIDEBAR_BG;
    border-top: 1px solid $SIDEBAR_BORDER;
}

#nowPlayingLabel {
    font-size: 13px;
    font-weight: 600;
    color: $TEXT;
}

QSlider::groove:horizontal {
    background: $BORDER;
    height: 4px;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background: $ACCENT;
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}

QSlider::sub-page:horizontal {
    background: $ACCENT;
    border-radius: 2px;
}
""")


def build_stylesheet() -> str:
    """Genera la QSS completa a partir de los tokens de arriba."""
    return _QSS.substitute({
        "ACCENT": ACCENT,
        "ACCENT_HOVER": ACCENT_HOVER,
        "BG": BG,
        "SIDEBAR_BG": SIDEBAR_BG,
        "SIDEBAR_BORDER": SIDEBAR_BORDER,
        "SURFACE": SURFACE,
        "SURFACE_HOVER": SURFACE_HOVER,
        "BORDER": BORDER,
        "BORDER_HOVER": BORDER_HOVER,
        "TEXT": TEXT,
        "TEXT_STRONG": TEXT_STRONG,
        "TEXT_SYNOPSIS": TEXT_SYNOPSIS,
        "TEXT_BREADCRUMB": TEXT_BREADCRUMB,
        "TEXT_DIM": TEXT_DIM,
        "TEXT_MUTED": TEXT_MUTED,
        "TEXT_FAINT": TEXT_FAINT,
        "RATING": RATING,
        "CARD_RADIUS": str(CARD_RADIUS),
    })
