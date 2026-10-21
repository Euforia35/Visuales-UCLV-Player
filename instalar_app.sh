#!/usr/bin/env bash
#
# instalar_app.sh — reconstruye "Visuales UCLV.app" en ~/Applications.
# Es el atajo para correr después de cada cambio en el proyecto: cierra la
# app si está abierta, la regenera y te confirma dónde quedó.
#
# Uso (desde la carpeta del proyecto):
#   ./instalar_app.sh                 # instala/actualiza la app
#   ./instalar_app.sh --acceso        # además (re)crea el acceso del Escritorio:
#                                     #   ~/Desktop/Instalar Visuales UCLV.command
#   ./instalar_app.sh --abrir         # instala y la abre al terminar
#
# Con el acceso del Escritorio creado, no hace falta escribir comandos:
# doble clic en "Instalar Visuales UCLV.command" y listo.
#
# Variables opcionales:
#   DESTINO=~/otra/carpeta   cambia dónde queda la app (por defecto ~/Applications)
#
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Visuales UCLV"
DESTINO="${DESTINO:-$HOME/Applications}"
APP_PATH="$DESTINO/${APP_NAME}.app"
ACCESO="$HOME/Desktop/Instalar ${APP_NAME}.command"

CREAR_ACCESO=0
ABRIR_APP="${ABRIR:-0}"
for arg in "$@"; do
    case "$arg" in
        --acceso) CREAR_ACCESO=1 ;;
        --abrir)  ABRIR_APP=1 ;;
        -h|--help)
            cat << 'AYUDA'
Uso: ./instalar_app.sh [--acceso] [--abrir]

Reconstruye "Visuales UCLV.app" en ~/Applications (o en $DESTINO si la definís).
  --acceso   además crea/actualiza el acceso de doble clic del Escritorio
             (~/Desktop/Instalar Visuales UCLV.command)
  --abrir    abre la app al terminar

Con el acceso del Escritorio ya creado, para reinstalar alcanza con
hacer doble clic en él — sin abrir la Terminal.
AYUDA
            exit 0
            ;;
        *)
            echo "Opción desconocida: $arg (usá --acceso, --abrir o --help)" >&2
            exit 1
            ;;
    esac
done

# --- Acceso de doble clic en el Escritorio ------------------------------
# Crea (o regenera) "Instalar Visuales UCLV.command" en el Escritorio. El
# archivo apunta a ESTA carpeta de proyecto; si el proyecto se mueve, hay
# que volver a generar el acceso desde la ubicación nueva.
crear_acceso_escritorio() {
    if [[ ! -d "$HOME/Desktop" ]]; then
        echo "⚠ No existe la carpeta ~/Desktop; no puedo crear el acceso." >&2
        return 1
    fi
    sed "s|@PROYECTO@|$PROJECT_DIR|g" > "$ACCESO" << 'ACCESO_CMD'
#!/usr/bin/env bash
# Acceso de doble clic creado por VisualesUCLV/instalar_app.sh.
# No hace falta editarlo a mano: se regenera con  ./instalar_app.sh --acceso
set -u
PROYECTO="${VISUALES_PROYECTO:-@PROYECTO@}"

if [[ ! -x "$PROYECTO/instalar_app.sh" ]]; then
    echo "✗ No encuentro el proyecto en: $PROYECTO"
    echo
    echo "Si moviste o renombraste la carpeta del proyecto, abrí una Terminal"
    echo "en la nueva ubicación y corré:  ./instalar_app.sh --acceso"
    echo "(eso vuelve a crear este acceso apuntando a la ruta nueva)."
    echo
    read -r -p "Presioná Enter para cerrar… " _
    exit 1
fi

if "$PROYECTO/instalar_app.sh"; then
    echo
    read -r -n 1 -s -p "✓ Terminado. Presioná una tecla para cerrar… " _
    echo
else
    echo
    read -r -p "✗ Algo falló (mirá los mensajes de arriba). Presioná Enter para cerrar… " _
    exit 1
fi
ACCESO_CMD
    chmod +x "$ACCESO"
    xattr -cr "$ACCESO" 2>/dev/null || true
    echo "➜ Acceso de doble clic en el Escritorio: $(basename "$ACCESO")"
}

# --- Reconstrucción de la app -------------------------------------------
# Si la app está abierta, la cierro primero para reemplazarla sin quedar
# con dos ventanas (el launcher es un proceso bash y Python corre como hijo).
# Se mata primero el launcher: si muere Python con error, el launcher
# mostraría un diálogo de "no pudo abrir" que no queremos al reinstalar.
if pgrep -f "$APP_PATH/Contents/MacOS/launcher" >/dev/null 2>&1; then
    echo "➜ La app está abierta; la cierro antes de reinstalar…"
    while read -r pid; do
        hijos="$(pgrep -P "$pid" 2>/dev/null || true)"
        kill -9 "$pid" 2>/dev/null || true   # launcher (bash) primero…
        if [[ -n "$hijos" ]]; then
            kill $hijos 2>/dev/null || true  # …y después Python (hijo)
            sleep 0.2
            kill -9 $hijos 2>/dev/null || true
        fi
    done < <(pgrep -f "$APP_PATH/Contents/MacOS/launcher" || true)
    for _ in 1 2 3 4 5 6 7 8; do
        pgrep -f "$APP_PATH/Contents/MacOS/launcher" >/dev/null 2>&1 || break
        sleep 0.25
    done
fi

VISUALES_APP_DIR="$DESTINO" "$PROJECT_DIR/build_app.sh"

if [[ "$CREAR_ACCESO" == "1" ]]; then
    crear_acceso_escritorio
fi

if [[ "$ABRIR_APP" == "1" ]]; then
    echo "➜ Abriendo la app…"
    open "$APP_PATH"
fi

echo
echo "✓ App actualizada en: $APP_PATH"
if [[ "$CREAR_ACCESO" != "1" && ! -f "$ACCESO" ]]; then
    echo "  Tip: ./instalar_app.sh --acceso crea un acceso de doble clic en el Escritorio."
fi
