# Changelog — Visuales UCLV

## 1.8.0
- **Reproductor embebido**: el video ahora se reproduce **dentro de la
  ventana de la app** (panel central del reproductor), con los
  controles debajo — sin ventana aparte de mpv. Se implementó con
  **libmpv + render API OpenGL** sobre un `QOpenGLWidget`
  (`mpv_embedded.py`), el mismo enfoque que clientes nativos como
  IINA. El camino viejo de `--wid` no existe en macOS; el render API
  evita además el problema histórico de las dos colas de eventos de
  Cocoa. Si libmpv no está disponible, la app cae automáticamente al
  mpv externo por IPC (o se fuerza con `VISUALES_PLAYER=external`).
  Nuevos atajos: Espacio (play/pausa), ←/→ (±10s), F (pantalla
  completa de la app), Esc (salir).
- **Modo cine en pantalla completa**: al entrar a pantalla completa con
  el reproductor embebido se oculta **toda** la interfaz (barra
  superior, fila de navegación, estado, botón "volver", barra de música
  y los propios controles) y queda solo el video. Los controles
  reaparecen al mover el mouse y se vuelven a esconder solos a los 3 s
  (estilo mpv); al salir de pantalla completa se restaura todo tal como
  estaba.
- **Hero del Inicio aleatorio y reciente**: el banner ya no sale casi
  siempre de `Peliculas/Cubanas`. Ahora se arma un pool ponderado por
  año (películas de `Extranjeras/2026`, `2025`, `2024`, `2023`, series
  con año reciente y lo publicado en `Recientes/`), se mezclan
  películas y series, y se elige al azar en cada carga del Inicio.
  Las tarjetas del banner llevan la URL completa: antes usaban la ruta
  interna del sitemap (`/Series/…`) y al hacer clic fallaban con
  «Invalid URL … No scheme supplied».
- **Búsqueda global desde `listado.html`**: la búsqueda por título usa
  el árbol de carpetas que publica el servidor, así que es instantánea
  — ya no indexa recursivamente todo el sitio ni mantiene un índice
  aparte. Los resultados son carpetas; el botón "🔄 Actualizar índice"
  solo vuelve a descargar el `listado.html`.
- **Navegación**: "Inicio" salió del menú "Explorar ▾"; ahora se llega
  haciendo clic en el logo **VISUALES UCLV** de la barra superior.
- **Favoritos**: nueva entrada "⭐ Favoritos" en el menú "Explorar ▾"
  (baja hasta la fila) y fila de Favoritos como **primera fila del
  Inicio**.
- El arranque del reproductor embebido ajusta `LC_NUMERIC=C` (sin eso
  libmpv puede hacer SIGSEGV en macOS) y la app sale con `os._exit` al
  cerrar, para no quedarse colgada esperando descargas de portadas en
  segundo plano.
- **Reinstalar sin comandos**: nuevo `instalar_app.sh`, que reconstruye
  la app en `~/Applications` cerrando antes la instancia abierta (sin
  diálogos de error ni procesos huérfanos). Con `--acceso` crea, una
  sola vez, `~/Desktop/Instalar Visuales UCLV.command`: doble clic para
  reinstalar después de cada cambio, sin abrir la Terminal.

## 1.7.0
- **Elegir subtítulos de la carpeta (pop-up)**: al abrir un video,
  si la carpeta tiene archivos de subtítulo (`.srt`, `.sub`, `.ass`,
  `.ssa`, `.vtt`), ahora aparece una ventana para escoger cuál (o
  cuáles) cargar — de nada sirve la carga automática cuando los
  nombres del sub. y del video no coinciden. Los que emparejan solos
  vienen pre-marcados; "Cancelar" mantiene el comportamiento anterior.
- Nuevo botón **📁 Subtítulos de la carpeta** en los controles del
  reproductor, para abrir ese mismo pop-up en cualquier momento (por
  ejemplo al continuar desde el historial, que no pasa por el pop-up).

## 1.6.1
- **Arreglo**: cuando mpv arrancaba bien pero fallaba al cargar el
  video (ventana vacía "Drop files or URLs to play here", típico con
  el sitio lento), no se avisaba nada. Ahora la app detecta ese caso
  (evento `end-file` con error de mpv) y muestra un aviso claro.
- El timeout de red de mpv subió de 30s a 60s, para tolerar mejor un
  servidor lento al empezar a reproducir.

## 1.6.0
- **Búsqueda global**: botón 🔍 (o Enter en el buscador) abre un
  diálogo que busca por título en TODO el servidor, no solo la
  carpeta actual. La primera vez indexa recursivamente todo el árbol
  de carpetas en segundo plano (puede tardar varios minutos según el
  tamaño del sitio) y lo guarda en caché para las próximas veces.
  Botón "🔄 Reindexar" para cuando se agregue contenido nuevo.

## 1.5.0
- **Descargar carpeta completa**: clic derecho sobre una carpeta →
  "⬇ Descargar toda esta carpeta". Recorre todas las subcarpetas,
  muestra cuántos archivos encontró y el tamaño total estimado antes
  de arrancar, y guarda todo respetando la estructura de carpetas del
  sitio dentro de `~/Downloads/VisualesUCLV/`.

## 1.4.2
- **Arreglo crítico (de nuevo)**: el fix 1.4.1 capturaba la salida de
  error de mpv con un pipe que nadie leía de forma continua — si mpv
  escribía suficiente ahí, se quedaba trabado esperando poder escribir
  (deadlock clásico), y el video nunca llegaba a reproducirse. Ahora
  esa salida se manda a un archivo temporal (nunca bloquea) en vez de
  un pipe.
- Además, ya no se depende de acertarle al nombre exacto de los flags
  de caché de mpv: si el arranque con esos flags falla por lo que sea,
  la app reintenta automáticamente sin ellos — mejor reproducir sin la
  optimización de caché que no reproducir nada.

## 1.4.1
- **Arreglo crítico**: el fix de caché de la versión anterior usaba
  `--cache-secs`, una opción de mpv vieja/renombrada en versiones
  recientes — hacía que NINGÚN video arrancara (mpv abría la ventana
  pero se quedaba en la pantalla de "Drop files", sin reproducir
  nada). Reemplazado por `--demuxer-readahead-secs`, el nombre actual
  vigente.
- Ya no se esconde la salida de error de mpv: si vuelve a fallar por
  cualquier motivo (flag inválido, archivo no encontrado, etc.), ahora
  se muestra el mensaje real de mpv en vez de fallar en silencio con
  una ventana vacía.
- El breadcrumb y los nombres guardados en Favoritos ahora decodifican
  bien los caracteres especiales de la URL (antes mostraban cosas como
  "El%20ser%20querido" en vez de "El ser querido").

## 1.4.0
- Nueva pestaña **Historial** ("Continuar viendo"): lista las series y
  películas con reproducción en progreso, con carátula, porcentaje
  visto y tiempo restante. Ahora es la pantalla que recibe al abrir la
  app (antes era "Inicio"). Clic derecho para quitar un ítem.
- Arreglo importante: al pasar la reproducción de mpv embebido a
  proceso aparte (v1.1.0), se perdieron sin querer los parámetros de
  caché/buffer para streaming. Esto hacía que videos largos empezaran
  bien pero se pusieran lentos/entrecortados después de un rato. Ya
  están de vuelta (colchón de 5 min, hasta 150MB de demuxer cache).

## 1.3.0
- La vista de detalle estilo Netflix (carátula + sinopsis + play) ahora
  también aplica a la carpeta "Series", no solo "Peliculas".
- La búsqueda de sinopsis en TMDb ahora sabe distinguir película vs.
  serie (usa el endpoint /search/tv para series, con su propio
  parámetro de año).
- Para series organizadas como `Serie/Temporada 1/`, la búsqueda en
  TMDb usa el nombre de la serie (carpeta padre) en vez del nombre de
  la temporada, para que encuentre el resultado correcto.

## 1.2.1
- La búsqueda de sinopsis ahora usa TMDb en vez de OMDb, porque TMDb sí
  devuelve el texto en español (OMDb solo tiene el original de IMDb,
  casi siempre en inglés, sin forma de traducirlo). Requiere una API
  Key de TMDb (distinta a la de OMDb si ya habías cargado una).

## 1.2.0
- Auto-avance: al terminar un video, si hay otro en la misma carpeta
  (orden alfabético), lo reproduce solo. Pensado para series.
- Botón "🌐 Subtítulos" en el reproductor: busca y descarga subtítulos
  online desde OpenSubtitles (requiere API Key gratuita propia).
- Botón "🎬 Buscar sinopsis en IMDb" en la vista de detalle: trae la
  sinopsis (y póster si falta) vía OMDb (requiere API Key gratuita
  propia).
- Se sacó el acceso directo a MP3s del sidebar.
- Base para la futura app de música (lectura de metadatos ID3/carátulas
  embebidas, cola de reproducción, búsqueda de letras) — todavía no
  conectada a la UI principal.

## 1.1.0
- Vista de detalle estilo Netflix para carpetas de Películas (carátula,
  sinopsis, botón de reproducir), sin el fondo panorámico.
- Categorías de acceso directo en el sidebar (Películas, Series,
  Infantiles).
- Favoritos y Descargas más compactos en el sidebar.
- Reemplazo de la reproducción embebida de mpv (causaba crashes en
  macOS) por mpv como proceso aparte, controlado por IPC — mucho más
  estable.
- Carga automática de subtítulos locales (misma carpeta, mismo nombre).
- Resume: recordar el punto de reproducción de cada video.
- Vista de grilla con carátulas, gestor de descargas.
- Validación de imágenes con Pillow antes de mostrarlas (evita crashes
  nativos de macOS con archivos corruptos).

## 1.0.0
- Primera versión: explorador de `visuales.uclv.cu`, reproducción vía
  mpv embebido, favoritos, búsqueda, empaquetado como `.app` de doble
  clic.
