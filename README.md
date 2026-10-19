# Visuales UCLV — Cliente de escritorio para macOS

App nativa (doble clic, sin navegador) para explorar y reproducir en
streaming el contenido de `visuales.uclv.cu`. Reproduce con **mpv**
(soporta mp4, mkv, avi, etc.), recuerda dónde quedaste en cada video,
muestra carátulas en vista de grilla, y permite descargar archivos con
progreso.

## Cómo funciona el video (importante)

mpv corre como **proceso aparte** de la app (igual que si escribieras
`mpv archivo.mp4` en la terminal) y se controla por control remoto vía
su socket IPC. El video aparece en **una ventana propia de mpv**, no
dentro de la ventana de la app — tus controles (play/pausa, seek,
volumen) viven en el panel de la app y manejan esa ventana desde afuera.

Se hizo así después de varias vueltas: embeber el video directamente
dentro de la ventana de Qt resultaba en crashes intermitentes en
macOS, porque tanto Qt como el backend de video de mpv necesitan
manejar la cola de eventos de Cocoa desde el hilo principal, y al
correr los dos DENTRO del mismo proceso terminan peleando por eso. Con
mpv en su propio proceso, cada uno tiene su propia cola de eventos y
no hay conflicto posible.

Por esto ya **no hace falta `python-mpv` ni `libmpv`** como dependencia
de Python — solo el programa `mpv` (el mismo que instala
`brew install mpv`), así que la instalación es más simple.

## Forma más fácil de correrla: `run.sh`

Este script instala TODO lo que falte (Homebrew, mpv, entorno virtual
de Python, dependencias) y después abre la app. Es seguro correrlo
todas las veces: si ya está todo instalado, simplemente lo detecta y
salta directo a abrir la app.

```bash
cd VisualesUCLV
chmod +x run.sh      # solo hace falta la primera vez
./run.sh
```

La primera vez puede tardar unos minutos (instala mpv vía Homebrew).
Las siguientes veces arranca en segundos.

> Si Homebrew no está instalado, el script te va a preguntar si querés
> instalarlo (pide tu contraseña de Mac, es normal — lo pide el
> instalador oficial de Homebrew, no algo de esta app).

## Instalación manual (si preferís hacerlo paso a paso)

```bash
brew install mpv
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

## Uso

- La app abre en **🕐 Historial** ("Continuar viendo"): todo lo que
  tenés a medio ver, con carátula y porcentaje. Clic para seguir donde
  quedaste, clic derecho para quitarlo de la lista. Botón "🏠 Inicio"
  para ir al catálogo completo.
- **Búsqueda global**: el buscador de arriba filtra la carpeta actual
  mientras escribís, pero si apretás **Enter** (o el botón 🔍 al lado)
  busca por título en TODO el servidor, no solo donde estás parado.
  La primera vez indexa todo el sitio en segundo plano (puede tardar
  según el tamaño), y después queda cacheado — "🔄 Reindexar" si se
  agregó contenido nuevo y querés actualizarlo.
- Doble clic en una carpeta → entra. Si la carpeta tiene un video +
  `sinopsis.txt`, se abre automáticamente una **vista de detalle estilo
  Netflix** (carátula, sinopsis, botón grande de reproducir) en vez del
  listado plano. Podés volver al listado de archivos crudo con el botón
  "📁 Ver todos los archivos" (útil para ver subtítulos sueltos, extras,
  etc.). Doble clic directo en un archivo de video reproduce.
- Clic derecho sobre un archivo → reproducir, descargar, u olvidar progreso.
- Botón ☆ arriba a la derecha → marca la carpeta actual como favorita
  (aparece en el sidebar).
- Botón "🖼 Vista grilla" → cambia el listado de archivos (no la vista
  de detalle) a una grilla con carátulas. Como descarga imágenes, si tu
  conexión es lenta o costosa conviene dejarlo en vista de lista.
- Las descargas aparecen en el sidebar con su progreso; clic derecho
  para cancelar o "Mostrar en Finder" cuando terminan. Se guardan en
  `~/Downloads/VisualesUCLV/`.
- Clic derecho sobre una carpeta → "⬇ Descargar toda esta carpeta"
  descarga TODO lo que hay adentro (recursivo, con subcarpetas
  incluidas), respetando esa misma estructura de carpetas al guardar.
  Te avisa cuántos archivos y el tamaño total estimado antes de
  arrancar.
- Si volvés a abrir un video que ya empezaste, te pregunta si querés
  continuar donde quedaste.
- Los subtítulos que estén en la misma carpeta que el video (mismo
  nombre, con o sin sufijo de idioma como `.es.srt`) se cargan solos al
  reproducir. Además, al abrir un video que tenga subtítulos en su
  carpeta aparece un **pop-up para elegir cuál cargar** (lista todos
  los `.srt`/`.ass`/etc. de la carpeta, aunque los nombres no tengan
  nada que ver con el del video); los que emparejan solos vienen
  pre-marcados y "Cancelar" deja la carga automática como siempre.
- **Auto-avance**: al terminar un video, si hay otro video después en
  la misma carpeta (orden alfabético), lo reproduce solo — pensado para
  series (episodio 1 → 2 → 3…).
- **Botón "📁 Subtítulos de la carpeta"** (en los controles del
  reproductor): abre ese mismo pop-up en cualquier momento — sirve
  cuando el video arrancó sin subtítulos (ej. desde el historial) o
  cuando cargaste los equivocados.
- **Botón "🌐 Subtítulos"** (en los controles del reproductor): busca
  subtítulos online en OpenSubtitles y los descarga/activa con un clic.
  La primera vez te pide una API Key gratuita (ver más abajo).
- **Botón "🎬 Buscar sinopsis en español (TMDb)"** (en la vista de
  detalle): busca la sinopsis en español en TMDb (The Movie Database)
  para cuando `sinopsis.txt` no está o no te convence la que hay.
  También pide una API Key gratuita la primera vez.

### API Keys gratuitas (subtítulos online + sinopsis en español)

Estas dos funciones dependen de servicios externos gratuitos que piden
registrarte (no hay forma de saltear esto, son servicios de terceros):

- **OpenSubtitles** (subtítulos): registrate como "Consumer" en
  <https://www.opensubtitles.com/en/consumers> y creá una API Key ahí.
  Es gratis e instantáneo. Sin iniciar sesión, la cuenta gratis tiene
  una cuota chica de descargas por día.
- **TMDb** (sinopsis en español): pedí una API Key gratis en
  <https://www.themoviedb.org/settings/api> (elegí "Developer"). A
  diferencia de OMDb (que solo tiene el texto en inglés de IMDb), TMDb
  sí devuelve la sinopsis en español cuando esa traducción existe
  cargada — que es el caso de la gran mayoría de películas conocidas.
  Si no hay traducción para un título puntual, cae de respaldo al
  inglés y te avisa.

La app te pide la clave la primera vez que usás cada función (con un
botón directo al link de registro) y la guarda localmente para no
volver a pedirla — queda en
`~/Library/Application Support/VisualesUCLV/config.json`.

## Actualizar tras bajar una versión nueva

Cada vez que te paso un zip nuevo:

```bash
cd ~/VisualesUCLV                                  # tu carpeta del proyecto
unzip -o ~/Downloads/VisualesUCLV.zip -d ~/Downloads
cp -r ~/Downloads/VisualesUCLV/* .
source venv/bin/activate
pip install -r requirements.txt                     # solo instala lo que falte/cambió
python3 main.py                                      # probala antes de regenerar la app
```

Fijate la versión actual en el archivo `VERSION` (o en `CHANGELOG.md`
para ver qué cambió). Después de probarla, regenerá el `.app` liviano
del Escritorio:

```bash
./build_app.sh
```

## Generar una app de doble clic (sin volver a tocar la Terminal)

Una vez que ya corriste `./run.sh` al menos una vez (o instalaste todo a
mano) y la app te abrió bien, generá el `.app` de doble clic:

```bash
chmod +x build_app.sh
./build_app.sh
```

Esto crea **"Visuales UCLV.app" en tu Escritorio**, con ícono propio
(un triángulo de play rojo sobre fondo oscuro). De ahí en adelante,
doble clic para abrir — no hace falta Terminal ni Python a la vista.

> La primera vez que la abras, macOS puede mostrar una advertencia de
> "desarrollador no identificado" (normal para apps no firmadas). Si
> pasa, hacé clic derecho sobre la app › Abrir, y confirmá una vez —
> las próximas veces abre directo con doble clic.

> Si más adelante movés o renombrás la carpeta del proyecto
> (`VisualesUCLV`), la app del Escritorio deja de encontrarla — volvé a
> correr `./build_app.sh` para regenerarla apuntando a la nueva ubicación.

**Importante:** esta app de doble clic sigue dependiendo de la carpeta
del proyecto y su `venv` (solo te ahorra la Terminal en tu propia Mac).
Para llevarla a OTRA computadora sin Python instalado, usá el `.dmg`
de la siguiente sección.

## Llevarla a otra Mac sin Python instalado (.dmg)

`build_app.sh` genera un lanzador liviano que depende de esta carpeta
y de Python — sirve para vos, pero no es portable. Para un `.dmg` que
funcione en cualquier Mac sin tener Python instalado, usá
`build_dmg.sh`, que empaqueta el intérprete de Python y todas las
librerías DENTRO de la app con `py2app`:

```bash
chmod +x build_dmg.sh
./build_dmg.sh
```

Puede tardar varios minutos la primera vez. El resultado es
`Visuales UCLV-<versión>.dmg` en la carpeta del proyecto — se lo pasás
a quien quieras, lo abre con doble clic, y arrastra la app al ícono de
Applications, como cualquier instalador de Mac.

> **La única dependencia que sigue haciendo falta en la Mac destino es
> `mpv`** (`brew install mpv`) — es un programa aparte, no una
> librería de Python, así que `py2app` no puede meterlo adentro del
> bundle. Es un solo comando, mucho más liviano que pedirle a alguien
> que instale Python + todo lo demás.

> **Aviso honesto:** no tengo forma de probar `py2app` ni `hdiutil`
> desde donde te escribo (son herramientas exclusivas de macOS). El
> script está armado con la sintaxis correcta y buenas prácticas, pero
> `py2app` + PySide6 a veces necesita algún ajuste puntual según la
> versión exacta de macOS/Python — si te tira algún error al correrlo,
> mandame el mensaje completo y lo resolvemos.

## Estructura del proyecto

```
run.sh              → arranque con auto-instalación de todo
main.py             → punto de entrada
apache_index.py     → parser del listado "Index of /..." de Apache
player.py           → reproductor embebido con mpv + controles
progress.py         → guarda el punto de reproducción (resume)
thumbnails.py        → busca/descarga carátulas para la vista de grilla
downloads.py         → gestor de descargas en segundo plano
main_window.py       → ventana principal: navegación, favoritos, grilla,
                       descargas, menús contextuales
style.qss            → tema visual oscuro
setup.py             → empaquetado con py2app
```

## Cosas a tener en cuenta

- El parser del listado y la heurística de carátulas están construidos
  contra el formato estándar de Apache mod_autoindex y convenciones
  típicas de Kodi (poster.jpg, folder.jpg, o una imagen con el mismo
  nombre que la carpeta/archivo). No pude probarlos contra el sitio
  real desde acá (su robots.txt bloquea crawlers automáticos), así que
  conviene correrlo y avisarme si algo no calza para ajustar la
  heurística.
- Las descargas van de a 2 simultáneas como máximo, para no saturar
  conexiones lentas.

## Próximos pasos posibles

- Descarga de carpetas completas (todos los episodios de una serie).
- Reanudar descargas interrumpidas.
- Integración con tu automatización de login de Nauta, para conectar
  el portal cautivo antes de abrir la app.

Contame qué de esto te interesa y seguimos.
