#!/usr/bin/env bash
#
# build_app.sh — genera "Visuales UCLV.app", una app de doble clic que
# arranca el proyecto usando el intérprete de Python que ya tiene las
# dependencias (por defecto el de Miniconda) + mpv. No empaqueta Python
# ni las librerías dentro del .app: simplemente lo lanza, así que evita
# los dolores de cabeza típicos de py2app con PySide6 + mpv.
#
# Uso (una sola vez, desde la carpeta del proyecto):
#   chmod +x build_app.sh
#   ./build_app.sh
#
# Esto crea "Visuales UCLV.app" en ~/Applications (NO en el Escritorio:
# macOS protege Escritorio/Documentos/Descargas y puede bloquear en
# silencio las apps sin firmar que corren desde ahí). Doble clic para
# abrir de ahí en adelante — no hace falta volver a tocar la Terminal.
#
# Importante: el .app queda apuntando a la carpeta del proyecto en la
# ubicación donde está AHORA MISMO. Si más adelante movés o renombrás
# esta carpeta, hay que volver a correr build_app.sh.
#
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="Visuales UCLV"
APP_DIR="${VISUALES_APP_DIR:-$HOME/Applications}"
APP_PATH="$APP_DIR/${APP_NAME}.app"

# Intérprete de Python con las dependencias instaladas. Se puede
# sobreescribir con PYTHON_BIN=… si tenés otro entorno preparado.
PYTHON_BIN="${PYTHON_BIN:-/opt/miniconda3/bin/python}"
if [[ ! -x "$PYTHON_BIN" ]]; then
    PYTHON_BIN="$(command -v python3 || true)"
fi
if [[ -z "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
    echo "⚠ No encuentro un intérprete de Python3. Instalá Miniconda o pasá PYTHON_BIN=/ruta/a/python."
    exit 1
fi
if ! "$PYTHON_BIN" -c "import PySide6" >/dev/null 2>&1; then
    echo "⚠ El intérprete $PYTHON_BIN no tiene PySide6 instalado."
    echo "  Instalá las dependencias: $PYTHON_BIN -m pip install -r requirements.txt"
    exit 1
fi

case "$APP_DIR" in
    "$HOME/Desktop"*|"$HOME/Documents"*|"$HOME/Downloads"*)
        echo "⚠ AVISO: la app se generaría dentro de una carpeta protegida de macOS"
        echo "  ($APP_DIR). El sistema puede bloquearla en silencio."
        echo "  Recomendado dejarla en ~/Applications (lo que hace por defecto)."
        echo ""
        read -p "¿Continuar de todas formas acá? [s/N] " resp
        if [[ ! "$resp" =~ ^[sS]$ ]]; then
            exit 1
        fi
        ;;
esac

APP_VERSION="$(cat "$PROJECT_DIR/VERSION" 2>/dev/null || echo "0.0.0")"

mkdir -p "$APP_DIR"
echo "➜ Creando $APP_PATH (versión $APP_VERSION) …"
rm -rf "$APP_PATH"
mkdir -p "$APP_PATH/Contents/MacOS"
mkdir -p "$APP_PATH/Contents/Resources"

cat > "$APP_PATH/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>cu.uclv.visuales.launcher</string>
    <key>CFBundleVersion</key>
    <string>${APP_VERSION}</string>
    <key>CFBundleShortVersionString</key>
    <string>${APP_VERSION}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>

    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>LSMinimumSystemVersion</key>
    <string>11.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
PLIST

cat > "$APP_PATH/Contents/MacOS/launcher" << LAUNCHER
#!/usr/bin/env bash
# Generado por build_app.sh — se regenera cada vez que lo corrés de nuevo.
PROJECT_DIR="${PROJECT_DIR}"
PYTHON_BIN="${PYTHON_BIN}"
LOG_FILE="/tmp/visualesuclv-launch.log"

fail() {
    local msg
    msg="\$(printf '%s' "\$1" | tr '\n' ' ' | sed "s/\\"/'/g")"
    /usr/bin/osascript -e "display alert \\"Visuales UCLV no pudo abrir\\" message \\"\$msg\\" as critical" >/dev/null 2>&1
    exit 1
}

if [[ ! -d "\$PROJECT_DIR" ]]; then
    fail "No se encontró la carpeta del proyecto en \$PROJECT_DIR. Si la moviste o renombraste, volvé a correr build_app.sh desde la nueva ubicación."
fi

cd "\$PROJECT_DIR" || fail "No se pudo entrar a la carpeta \$PROJECT_DIR"

if [[ ! -x "\$PYTHON_BIN" ]]; then
    fail "No se encontró el intérprete de Python en \$PYTHON_BIN. Si cambió de ruta, volvé a correr build_app.sh."
fi

if ! "\$PYTHON_BIN" -c "import PySide6" >/dev/null 2>&1; then
    fail "\$PYTHON_BIN no tiene PySide6. Instalá las dependencias con: \$PYTHON_BIN -m pip install -r requirements.txt"
fi

"\$PYTHON_BIN" main.py > "\$LOG_FILE" 2>&1
STATUS=\$?

if [[ \$STATUS -ne 0 ]]; then
    fail "\$(tail -c 1200 "\$LOG_FILE")"
fi
LAUNCHER

chmod +x "$APP_PATH/Contents/MacOS/launcher"

# Genera el ícono (.icns) a partir de icon.png usando las herramientas
# nativas de macOS (sips + iconutil). Si por algún motivo no están
# disponibles, la app igual funciona, solo que con el ícono genérico.
if [[ -f "$PROJECT_DIR/icon.png" ]] && command -v sips >/dev/null && command -v iconutil >/dev/null; then
    echo "➜ Generando ícono…"
    ICONSET_DIR="$(mktemp -d)/AppIcon.iconset"
    mkdir -p "$ICONSET_DIR"
    for size in 16 32 128 256 512; do
        sips -z $size $size "$PROJECT_DIR/icon.png" --out "$ICONSET_DIR/icon_${size}x${size}.png" >/dev/null
        double=$((size * 2))
        sips -z $double $double "$PROJECT_DIR/icon.png" --out "$ICONSET_DIR/icon_${size}x${size}@2x.png" >/dev/null
    done
    iconutil -c icns "$ICONSET_DIR" -o "$APP_PATH/Contents/Resources/AppIcon.icns"
    rm -rf "$(dirname "$ICONSET_DIR")"
else
    echo "⚠ No se generó ícono personalizado (falta icon.png o sips/iconutil); se usa el genérico."
fi

# Quita el atributo de cuarentena que macOS pone a lo creado por scripts,
# para que no aparezca la advertencia de "desarrollador no identificado"
# la primera vez que se abre.
xattr -cr "$APP_PATH" 2>/dev/null || true

echo "✓ Listo: \"${APP_NAME}.app\" (v${APP_VERSION}) está en $APP_DIR."
echo "  Doble clic para abrir. Si igual aparece una advertencia de macOS"
echo "  la primera vez, hacé clic derecho sobre la app › Abrir."
