# Monitor de textos web

Programa de terminal para macOS que observa una zona concreta de una página web, detecta cuándo
**aparece**, **desaparece** o **cambia** un texto definido por ti (por ejemplo `online` ↔ `offline`)
y guarda cada cambio, con fecha y hora, en un historial CSV que se abre con Excel.

* Genérico: la URL, el elemento, los textos y los estados se definen en un archivo de configuración.
* Dos formas de leer la página: **navegador real** (Playwright) o **HTTP** (requests + BeautifulSoup).
  El comando `probe` indica cuál necesita tu página.
* Distingue un texto que de verdad desapareció de una página que no se pudo leer.
* Confirma los cambios con varias observaciones, no repite eventos y se puede detener y reanudar
  sin perder el historial.

> **Estado de verificación.** Las 121 pruebas automatizadas, las pruebas de concepto y una ejecución
> completa contra la página de demostración se ejecutaron en **Linux** (Python 3.13 y 3.11,
> Playwright 1.56.0, Chromium 141). **No se ha ejecutado en un Mac ni contra tu página real**,
> que aún no se ha definido. La [lista de validación](#lista-de-validación) sirve para comprobarlo en
> tu MacBook.

**Documentos:** [análisis de viabilidad, diseño y prueba de concepto](docs/ANALISIS_Y_DISENO.md) ·
[resultados reales de las pruebas](docs/RESULTADOS_PRUEBAS.md) ·
[configuración comentada](config.example.toml)

---

## Índice

1. [Instalación en macOS (Apple Silicon)](#1-instalación-en-macos-apple-silicon)
2. [Primera prueba con la página de demostración](#2-primera-prueba-con-la-página-de-demostración)
3. [Configurar tu página](#3-configurar-tu-página)
4. [Iniciar y detener el monitor](#4-iniciar-y-detener-el-monitor)
5. [El historial CSV](#5-el-historial-csv)
6. [Páginas que requieren iniciar sesión](#6-páginas-que-requieren-iniciar-sesión)
7. [Pruebas automatizadas](#7-pruebas-automatizadas)
8. [Lista de validación](#lista-de-validación)
9. [Solución de problemas](#9-solución-de-problemas)
10. [Limitaciones](#10-limitaciones)
11. [Seguridad y uso responsable](#11-seguridad-y-uso-responsable)
12. [Estructura del proyecto](#12-estructura-del-proyecto)

---

## 1. Instalación en macOS (Apple Silicon)

Todos los comandos se escriben en la aplicación **Terminal** (Aplicaciones → Utilidades → Terminal).
No hace falta Homebrew.

### 1.1 Comprobar Python

```bash
python3 --version
```

El programa necesita **Python 3.11 o posterior**. El `python3` que trae macOS con las herramientas
de línea de comandos suele ser 3.9, que **no sirve**: el programa lo detecta y muestra un aviso.
Si tu versión es anterior a 3.11:

1. Descarga el instalador **macOS 64-bit universal2** de Python 3.13 desde
   <https://www.python.org/downloads/macos/> (funciona de forma nativa en Apple Silicon).
2. Ábrelo y sigue los pasos.
3. Cierra la Terminal, ábrela de nuevo y comprueba:

```bash
python3.13 --version
```

En el resto de pasos se usa `python3.13`. Si instalaste otra versión ≥ 3.11, cambia el número.

### 1.2 Crear la carpeta del proyecto

El proyecto está en la carpeta `web_text_monitor/` del repositorio. Por ejemplo, para dejarlo en
`~/Proyectos/web_text_monitor`:

**Opción A: con git** (si macOS pide instalar las herramientas de línea de comandos, acepta):

```bash
mkdir -p ~/Proyectos
cd ~/Proyectos
git clone --branch claude/stoic-davinci-dgbje3 https://github.com/santoriniiiii/code.git repo-code
cp -R repo-code/web_text_monitor ~/Proyectos/web_text_monitor
cd ~/Proyectos/web_text_monitor
```

**Opción B: sin git.** Descarga el ZIP del repositorio desde GitHub (botón *Code → Download ZIP*),
descomprímelo y copia la carpeta `web_text_monitor` a `~/Proyectos/`. Después:

```bash
cd ~/Proyectos/web_text_monitor
```

### 1.3 Crear y activar el entorno virtual

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python --version          # debe mostrar 3.13.x
```

El indicador `(.venv)` aparece al principio de la línea. **Cada vez que abras una Terminal nueva**,
entra en la carpeta y vuelve a activar el entorno:

```bash
cd ~/Proyectos/web_text_monitor && source .venv/bin/activate
```

### 1.4 Instalar las dependencias

```bash
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
```

`requirements.txt` contiene lo necesario para usar el programa (playwright, requests,
beautifulsoup4). `requirements-dev.txt` añade pytest para las pruebas.

### 1.5 Instalar el navegador de Playwright

```bash
python -m playwright install chromium
```

Descarga una versión de Chromium para Apple Silicon (varios cientos de MB) en
`~/Library/Caches/ms-playwright`. No modifica tu Chrome ni tu Safari. Si prefieres usar el Google
Chrome que ya tienes instalado, pon `channel = "chrome"` en `[browser]`.

### 1.6 Ejecutar las pruebas

```bash
python -m pytest
```

El resultado esperado es `121 passed`. Las pruebas no acceden a internet: usan datos simulados,
archivos temporales y un servidor local en 127.0.0.1. Si Chromium no estuviera instalado, las 13
pruebas con navegador aparecerían como *skipped*.

---

## 2. Primera prueba con la página de demostración

Antes de usar tu página, comprueba el programa completo con la demostración local. Su estado alterna
entre `online` y `offline` cada 30 segundos.

**Terminal 1:**

```bash
cd ~/Proyectos/web_text_monitor && source .venv/bin/activate
python main.py demo-server
```

**Terminal 2:**

```bash
cd ~/Proyectos/web_text_monitor && source .venv/bin/activate
python main.py --config config.demo.toml run
```

Verás mensajes con este formato. Es un ejemplo: las horas y la secuencia dependerán de tu ejecución.

```
[10:22:03] Estableciendo línea base: online (1/2)
[10:22:08] Línea base establecida: online (texto detectado: online)
[10:22:13] Sin cambios (online).
[10:22:33] Posible cambio: online -> offline (1/2), pendiente de confirmación.
[10:22:38] CAMBIO DETECTADO: online -> offline
[10:22:38]   Texto desaparecido: online
[10:22:38]   Texto detectado: offline
```

Pulsa **Ctrl+C** en la terminal 2 para detener el monitor y mira el historial:

```bash
open data/demo_events.csv
```

Para probar los errores, reinicia el servidor con `python main.py demo-server --periodo 15 --con-errores`:
añade una fase en la que responde HTTP 503. Deberías ver
`No se pudo leer (el servidor respondió HTTP 503); el estado anterior se conserva.` y, después,
`Lectura restablecida`.

---

## 3. Configurar tu página

### 3.1 Crear el archivo de configuración

```bash
cp config.example.toml config.toml
```

Edita `config.toml` con un editor de texto plano: `nano config.toml` en la Terminal, Visual Studio
Code o BBEdit. **Si usas TextEdit**, desactiva antes *Edición → Sustituciones → Comillas
inteligentes*: las comillas tipográficas (“ ”) estropean el archivo.

Cada opción está explicada en [`config.example.toml`](config.example.toml). Lo mínimo:

```toml
[page]
url = "https://tu-pagina.example/estado"

[extraction]
selector = "#estado"      # ¡compruébalo en tu página! (ver 3.2)

[[targets]]
id = "online"
text = "online"
mode = "word"

[[targets]]
id = "offline"
text = "offline"
mode = "word"
```

Los textos `online`/`offline` son un ejemplo: cámbialos por cualquier texto sin tocar el código.
Varios textos pueden representar el mismo estado (`state = "online"` en `"en línea"` y en
`"online"`).

### 3.2 Encontrar el selector del elemento

1. Abre la página en Chrome, pulsa **⌥⌘I** y después **⇧⌘C**, y haz clic sobre el texto.
2. En el nodo resaltado (o en un antecesor cercano), busca un `id`, un `data-testid` u otro
   atributo estable. Evita clases con aspecto aleatorio y selectores con posiciones (`nth-child`).
3. Compruébalo en la pestaña *Console*: `document.querySelectorAll('#estado').length` debe dar `1`.
4. Si el nodo está dentro de un `<iframe>`, añade el selector del iframe en `frame_selectors`.

O deja que el programa lo busque en la página real:

```bash
python main.py probe --find "online"
```

Para `--find` el selector configurado puede ser provisional (por ejemplo `selector = "body"`). La
explicación detallada está en [A.4 del análisis](docs/ANALISIS_Y_DISENO.md#a4-cómo-identificar-el-elemento-con-las-herramientas-de-desarrollo).

### 3.3 Comprobar la configuración y la página

```bash
python main.py check     # valida config.toml sin acceder a la página
python main.py probe     # lee la página con y sin navegador y recomienda un método
```

`probe` indica si el texto está en el HTML estático (bastaría `method = "http"`), si hace falta
JavaScript, si hay iframes, si el texto cambia justo después de cargar (`settle_seconds`) y si cambia
sin recargar (`reload_each_check = false`). Añade `--headed` para ver la ventana del navegador.

### 3.4 Opciones principales

| Necesidad | Opción |
|---|---|
| Intervalo de comprobación | `[schedule] interval_seconds` (5 por defecto, mínimo 1) |
| Leer con navegador o solo HTTP | `[extraction] method = "browser" \| "http"` |
| Elemento dentro de un iframe | `[extraction] frame_selectors = ["iframe#panel"]` |
| Varios elementos (filas de una tabla) | `[extraction] match_policy = "all"` |
| Solo el texto visible | `[extraction] text_source = "visible"` (por defecto) |
| ¿Elemento ausente = texto ausente? | `[extraction] element_missing = "unknown" \| "absent"` |
| Recargar o no la página | `[extraction] reload_each_check` |
| Página con marcador "Cargando…" | `[extraction] settle_seconds = 2` o `reload_each_check = false` |
| Mayúsculas y espacios | `[matching] case_sensitive`, `whitespace` |
| Varios estados a la vez | `[matching] multiple_states = "conflict" \| "priority" \| "combined"` |
| Ningún texto presente | `[matching] no_match = "state" \| "unknown"` |
| Palabra completa ("available" ≠ "unavailable") | `mode = "word"` en el `[[targets]]` |
| Observaciones para confirmar un cambio | `[confirmation] required_observations` (2 por defecto) |
| Lecturas fallidas mientras se confirma | `[confirmation] unknown_policy = "ignore" \| "reset"` |
| Nueva línea base tras un corte largo | `[confirmation] rebaseline_after_failures` |
| Reanudar tras reiniciar | `[confirmation] resume_state` |
| Política ante errores | `[errors] backoff_max_seconds`, `max_consecutive_errors` |
| Rutas, zona horaria, separador CSV | `[output] csv_path`, `timezone`, `csv_delimiter` |
| Qué eventos se guardan | `[output] record_events` |
| Detalle de los mensajes | `[output] terminal = "quiet" \| "normal" \| "verbose"`, `log_level` |

Las rutas relativas se interpretan respecto a la carpeta del archivo de configuración. Si hay algún
error (clave mal escrita, valor no válido...), el programa lista **todos** los problemas y no arranca.

---

## 4. Iniciar y detener el monitor

```bash
python main.py run                          # usa config.toml
python main.py --config otra.toml run       # otra configuración
```

Al empezar muestra el nombre y la versión, la URL, el elemento, los textos, el intervalo, la ruta del
historial y el estado. **Para detenerlo, pulsa Ctrl+C una vez**: termina la comprobación en curso,
guarda el estado, escribe `MONITOR_STOPPED` y cierra el navegador. Un segundo Ctrl+C fuerza la salida.
El CSV no queda a medias porque cada fila se escribe completa y se fuerza a disco.

Al volver a ejecutarlo continúa con el mismo historial. Si el estado era el mismo, no se escribe
nada nuevo. Si cambió mientras estaba detenido, se registra el cambio indicando entre qué dos
momentos ocurrió.

**Que el Mac no entre en reposo:** con el equipo en reposo no se observa nada. El programa avisa a la
vuelta ("No se observó la página durante X s"). Para evitar el reposo por inactividad, abre otra
ventana de Terminal y ejecuta `caffeinate -i`; termínalo con Ctrl+C cuando acabes. Cerrar la tapa
suspende el Mac igualmente.

Códigos de salida: `0` normal, `2` error de configuración o de arranque, `3` demasiados errores
seguidos, `130` salida forzada.

---

## 5. El historial CSV

* Ubicación por defecto: `data/events.csv` (ábrelo con `open data/events.csv`).
* Se crea solo si no existe y **nunca se sobrescribe**: cada ejecución añade filas.
* Codificación UTF-8 con BOM para que Excel muestre bien tildes y eñes.
* Solo se escriben filas cuando hay un evento relevante, nunca una por comprobación.
* Los errores técnicos detallados van a `logs/application.log`.

**Importante:** no guardes el CSV desde Excel. Excel puede cambiar el formato y el monitor dejaría
de escribir en él para no dañarlo. Para analizarlo, haz una copia:
`cp data/events.csv ~/Desktop/eventos.csv`. Si Excel muestra todas las columnas juntas, impórtalo
con *Datos → Desde texto/CSV*, o configura `csv_delimiter = ";"` con un archivo **nuevo** (no cambies
el separador de un CSV que ya tiene datos).

### Columnas

| Columna | Contenido |
|---|---|
| `id_evento` | Identificador único (UUID) |
| `fecha_hora_utc` | ISO 8601 en UTC, p. ej. `2026-10-14T15:22:08.998+00:00` |
| `fecha_hora_local` | ISO 8601 en la zona configurada, p. ej. `2026-10-14T10:22:08.998-05:00` |
| `fecha_local`, `hora_local` | Fecha y hora locales separadas (cómodas para filtrar en Excel) |
| `zona_horaria` | `America/Lima` por defecto |
| `tipo_evento` | Ver la tabla siguiente |
| `pagina`, `url`, `selector` | Qué se observaba |
| `texto_buscado` | Texto(s) configurado(s) a los que se refiere el evento |
| `texto_anterior`, `texto_nuevo` | Texto encontrado en la página, tal como aparecía (p. ej. `Online`) |
| `estado_anterior`, `estado_nuevo` | Estados según tu configuración |
| `observaciones_confirmacion` | Observaciones seguidas que confirmaron el cambio |
| `duracion_observacion_ms` | Tiempo que tardó la lectura que confirmó el evento |
| `metodo_deteccion` | Navegador o HTTP, tipo de texto y modo de coincidencia |
| `ultima_obs_estado_anterior_utc` | Última vez que se vio el estado anterior |
| `primera_obs_estado_nuevo_utc` | Primera vez que se vio el estado nuevo |
| `extracto_texto` | Inicio del texto del elemento (configurable; 0 = no se guarda) |
| `detalle` | Explicación o mensaje de error |
| `id_transicion` | Agrupa las filas del mismo cambio |
| `id_sesion` | Identifica cada ejecución del programa |

El cambio ocurrió en algún momento entre `ultima_obs_estado_anterior_utc` y
`primera_obs_estado_nuevo_utc`. El monitor solo puede saber cuándo lo **observó**.

### Tipos de evento

| Tipo | Significado |
|---|---|
| `BASELINE` | Estado inicial observado (no es un cambio) |
| `TEXT_APPEARED` | Un texto configurado apareció |
| `TEXT_DISAPPEARED` | Un texto configurado desapareció (con la página leída correctamente) |
| `STATE_CHANGED` | El estado cambió, p. ej. `online → offline` |
| `UNKNOWN` | La página se leyó pero no permite saber el estado (una fila por episodio) |
| `ERROR` | No se pudo leer la página (una fila por episodio) |
| `RECOVERED` | La lectura volvió a funcionar |
| `MONITOR_STARTED` / `MONITOR_STOPPED` | Inicio y fin de cada ejecución |
| `NO_CHANGE` | Solo en la terminal; nunca se guarda |

---

## 6. Páginas que requieren iniciar sesión

1. En `config.toml`, pon `user_data_dir = "data/browser_profile"` en `[browser]`.
2. Ejecuta `python main.py login`. Se abre una ventana del navegador con la página.
3. Inicia sesión **a mano**, como siempre. El programa no ve ni guarda tu contraseña.
4. Vuelve a la Terminal y pulsa Enter. La sesión queda guardada en el perfil.
5. Comprueba con `python main.py probe` y empieza con `python main.py run`.

Ten en cuenta:

* La carpeta del perfil contiene tus cookies de sesión: equivale a tener la sesión abierta. Se crea
  con permisos solo para tu usuario (`700`) y está excluida de git (`data/`). No la compartas ni la
  guardes en iCloud, Dropbox o similares. Activa FileVault (*Ajustes del Sistema → Privacidad y
  seguridad*).
* Cuando la sesión caduque, la página mostrará otra cosa (normalmente el formulario de acceso): el
  monitor registrará `UNKNOWN` (no un cambio) y tendrás que repetir `login`.
* Un perfil no se puede usar a la vez desde dos programas: cierra la ventana de `login` antes de `run`.
* Algunos sitios no permiten iniciar sesión desde navegadores automatizados. No intentes eludirlo.

La función `login` (ventana visible) no se ha podido ejecutar en el entorno de pruebas, que no tiene
pantalla. Sí se ha probado, sin ventana, que el perfil persistente conserva las cookies entre
ejecuciones y que no se puede abrir dos veces.

---

## 7. Pruebas automatizadas

```bash
python -m pytest            # todas
python -m pytest -v         # con el nombre de cada prueba
python -m pytest -m "not browser"   # solo las que no abren el navegador
```

| Archivo | Qué prueba | Red / navegador |
|---|---|---|
| `test_text_detector.py` | Normalización, mayúsculas, modos, varios textos, elemento ausente | No |
| `test_state_machine.py` | Línea base, aparición, desaparición, sustitución, confirmación, errores, reinicio, duplicados | No |
| `test_event_logger.py` | CSV: creación, BOM, conservación, errores de escritura, bloqueo, zonas horarias | No |
| `test_monitor.py` | Bucle: deriva del intervalo, espera tras errores, Ctrl+C, reinicio, reposo | No |
| `test_config.py` | Validación de la configuración | No |
| `test_integration_http.py` | requests + BeautifulSoup y el programa completo con SIGINT | Servidor local |
| `test_integration_browser.py` | Playwright: JavaScript, iframes, texto oculto, 503, caída del navegador, perfil, SIGINT | Servidor local + Chromium |

Los 16 casos pedidos y la prueba que cubre cada uno, junto con la salida real de la ejecución, están
en [docs/RESULTADOS_PRUEBAS.md](docs/RESULTADOS_PRUEBAS.md). Resultado en Linux:
**121 passed** con Python 3.13.16 y con Python 3.11.15.

Las pruebas con datos simulados validan el motor (detector, máquina de estados, CSV, bucle). **No**
sustituyen a una prueba con tu página real: para eso está la lista de validación.

---

## Lista de validación

Marca cada punto en tu Mac. Entre paréntesis, el comando o la comprobación.

**Instalación**
- [ ] `python --version` dentro del entorno virtual muestra 3.11 o posterior.
- [ ] `python -m pytest` termina con `121 passed` (sin *skipped*).
- [ ] `python poc/poc_ctrl_c.py` muestra, en la variante `sin_senales`, "lectura después de SIGINT OK".
      Así se confirma en macOS lo que se verificó en Linux.

**Demostración local**
- [ ] Con `demo-server` y `--config config.demo.toml run`, aparece `Línea base establecida`.
- [ ] Cada ~30 s aparece `CAMBIO DETECTADO`, confirmado tras 2 observaciones.
- [ ] Durante los periodos sin cambios, la terminal muestra "Sin cambios" y el CSV **no** crece.
- [ ] Al detener `demo-server`, aparece "No se pudo leer…" **una vez** en el CSV (`ERROR`) y ningún
      `TEXT_DISAPPEARED`. Al relanzarlo, aparece `RECOVERED`.
- [ ] Ctrl+C detiene el monitor en pocos segundos y la última fila del CSV es `MONITOR_STOPPED`.
- [ ] Al volver a ejecutar `run`, el CSV conserva las filas anteriores y no se repite la `BASELINE`.
- [ ] `data/demo_events.csv` se abre en Excel con las tildes correctas y la hora local de Lima.

**Tu página**
- [ ] `python main.py check` no muestra errores.
- [ ] `python main.py probe` encuentra **1** elemento con tu selector (o el número que esperas).
- [ ] La interpretación de `probe` coincide con lo que ves en la página.
- [ ] Si `probe` indica que basta `method = "http"`, repite `probe` en otro estado antes de cambiarlo.
- [ ] Con la página en cada estado, `run` muestra el estado correcto.
- [ ] Cuando cambia el texto real, aparece `CAMBIO DETECTADO` y la fila correspondiente en el CSV.
- [ ] Con la Wi-Fi desactivada un momento, se registra `ERROR` y **no** un cambio; al reactivarla, `RECOVERED`.
- [ ] Si la página requiere sesión: tras `login`, `probe` encuentra el elemento sin pedir contraseña.
- [ ] `logs/application.log` no contiene errores inesperados (`Traceback`).

---

## 9. Solución de problemas

| Síntoma | Causa probable y solución |
|---|---|
| `Este programa necesita Python 3.11 o posterior` | Estás usando el Python del sistema. Instala Python 3.13 (sección 1.1) y recrea el entorno: `rm -rf .venv && python3.13 -m venv .venv` |
| `command not found: python` | Activa el entorno: `source .venv/bin/activate` |
| `ModuleNotFoundError: No module named 'playwright'` | Entorno no activado o dependencias sin instalar: `pip install -r requirements.txt` |
| `No se encontró el navegador de Playwright` | `python -m playwright install chromium` |
| `CERTIFICATE_VERIFY_FAILED` | Ejecuta *Install Certificates.command* de la carpeta `/Applications/Python 3.13/` |
| `La configuración … no es válida` | Lee la lista de problemas; suele ser una clave mal escrita o comillas tipográficas |
| `probe` encuentra 0 elementos | Selector incorrecto, contenido dentro de un iframe (`frame_selectors`), página que exige sesión o contenido que tarda (`element_timeout_seconds`) |
| Siempre `UNKNOWN … coincide con N elementos` | El selector es demasiado general: hazlo más específico o usa `match_policy` |
| Siempre `sin_coincidencia` aunque se ve el texto | Mayúsculas o espacios distintos, o un marcador "Cargando…": usa `settle_seconds` o `reload_each_check = false` |
| Detecta dos estados a la vez (conflicto) | Un texto contiene al otro ("available" en "unavailable"): usa `mode = "word"` o `"exact"` |
| `Otro monitor ya está escribiendo en …` | Ya hay un monitor con ese CSV. Si no, quedó un proceso: búscalo con `ps aux \| grep main.py` |
| `El archivo … ya existe pero sus columnas o su separador no coinciden` | El CSV se guardó desde Excel o cambió `csv_delimiter`: usa otro `csv_path` |
| `AVISO: no se pudo escribir en …` | Disco lleno, permisos o archivo bloqueado. Las filas se reintentan y, si al salir siguen sin guardarse, se copian en `logs/application.log` |
| `El perfil … parece estar en uso` | Cierra la ventana de `login` u otro monitor que use el mismo `user_data_dir` |
| Errores HTTP 403/429 | El sitio limita el acceso automatizado o la frecuencia: aumenta el intervalo y consulta al responsable del sitio. No intentes eludirlo |
| macOS pregunta si permitir conexiones entrantes a "Chromium" | No hacen falta: puedes denegarlo |

Para ver más detalle: `terminal = "verbose"` y `log_level = "DEBUG"` en `[output]`.

---

## 10. Limitaciones

* **Cambios entre observaciones:** un texto que aparece y desaparece en menos de un intervalo puede
  no detectarse. Con `required_observations = 2` hace falta que dure al menos un intervalo más.
* **Momento exacto:** el CSV indica entre qué dos observaciones ocurrió el cambio, no el instante.
* **Varias observaciones coherentes aumentan la consistencia, no garantizan la corrección**: si la
  página muestra un dato erróneo de forma estable, se registrará.
* **Cambios en el diseño de la web:** si el sitio cambia su HTML, el selector puede dejar de
  coincidir (`UNKNOWN`) o, peor, coincidir con otro elemento. Revisa los `UNKNOWN` persistentes y
  vuelve a ejecutar `probe` tras un rediseño.
* **Visibilidad:** con `text_source = "visible"` se excluye lo oculto con `display:none`,
  `visibility:hidden` o tamaño cero. No se detecta texto "oculto" de otras formas (mismo color que el
  fondo, `opacity: 0`, fuera de la pantalla).
* **Interacción:** el monitor no hace clics, no rellena formularios y no se desplaza por la página.
* **Shadow DOM:** los selectores CSS de Playwright entran en el Shadow DOM abierto. Apunta el selector
  al elemento interior y compruébalo con `probe`.
* **Método HTTP:** no ejecuta JavaScript, no entra en iframes y no evalúa el CSS.
* **Reposo del Mac:** con el equipo suspendido no se observa.
* **Sesiones:** caducan según la política del sitio. El programa no puede renovarlas.
* **Zona horaria:** la zona configurada (America/Lima, UTC−5 sin horario de verano) solo afecta a
  las columnas locales; las columnas UTC son la referencia.

---

## 11. Seguridad y uso responsable

* Úsalo solo con páginas a las que tienes **acceso legítimo** y respetando sus condiciones de uso.
* El programa no elude controles de acceso, CAPTCHAs ni límites de peticiones, no guarda
  contraseñas y no envía datos a terceros: todo queda en tu Mac.
* Solo se guarda la parte relevante del texto. Con `excerpt_max_chars = 0` no se guarda ningún
  extracto.
* Un intervalo de 5 s recargando la página son 720 cargas completas de la página por hora. Si la página se actualiza
  sola, usa `reload_each_check = false`. Si no necesitas tanta frecuencia, aumenta el intervalo.
* `config.toml`, `data/` y `logs/` están excluidos de git porque pueden contener URLs privadas, datos
  de la página o la sesión del navegador.

---

## 12. Estructura del proyecto

```
web_text_monitor/
├── main.py                 Punto de entrada
├── config.example.toml     Configuración documentada (copiar a config.toml)
├── config.demo.toml        Configuración de la demostración
├── requirements.txt        Dependencias (versiones probadas)
├── requirements-dev.txt    + pytest
├── pytest.ini
├── textmonitor/            Código (un módulo por responsabilidad)
├── poc/                    Pruebas de concepto
├── tests/                  Pruebas automatizadas
├── docs/                   Análisis, diseño y resultados de las pruebas
├── data/                   Historial, estado y perfil del navegador (no se sube a git)
└── logs/                   Log técnico (no se sube a git)
```

La responsabilidad de cada módulo y el diseño completo están en
[docs/ANALISIS_Y_DISENO.md](docs/ANALISIS_Y_DISENO.md#b1-arquitectura).
