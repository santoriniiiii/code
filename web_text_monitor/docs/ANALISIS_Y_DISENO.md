# Análisis de viabilidad, diseño técnico y prueba de concepto

Este documento corresponde a los entregables **A**, **B** y **C**. La instalación, el uso,
las pruebas y la lista de validación están en el [README](../README.md).

> **Qué está verificado y qué no.** Todo lo que se presenta como resultado se ejecutó de verdad
> en un contenedor **Linux x86_64** con Python 3.13.16 y 3.11.15, Playwright 1.56.0 y Chromium
> 141.0.7390.37, contra páginas **locales** (127.0.0.1). **No** se ha ejecutado en un Mac ni
> contra tu página real, que todavía no se ha definido. La sección [A.3](#a3-qué-necesito-de-ti)
> explica qué información hace falta y cómo obtenerla.

---

## A. Análisis de viabilidad

### A.1 Qué herramienta hace falta en cada caso

| Situación | requests + BeautifulSoup | Playwright (navegador real) | Cómo saberlo |
|---|---|---|---|
| El texto está directamente en el HTML | **Sí** (suficiente y más ligero) | Sí, pero no hace falta | "Ver código fuente" (⌥⌘U) contiene el texto; `probe`, sección 1 |
| El texto aparece después de ejecutar JavaScript | **No**: solo ve el marcador inicial (verificado: `Cargando…`) | **Sí** | Está en "Inspeccionar", pero no en "Ver código fuente" |
| El texto se actualiza sin recargar la página | Solo si cada nueva descarga del HTML trae el valor actual | **Sí**, leyendo el DOM sin recargar (`reload_each_check = false`) | `probe` hace varias lecturas sin recargar |
| El texto aparece o desaparece según un evento (clic, *hover*, desplazamiento) | No | Solo si el evento ocurre sin intervención: **esta versión no hace clics** | Observación manual |
| El texto está en un elemento concreto | Sí (selector CSS) | Sí (CSS, XPath y selectores de Playwright) | Herramientas de desarrollo |
| Forma parte de una tabla, panel, etiqueta o sección | Sí | Sí | `match_policy = "all"` para varias filas o celdas |
| Está dentro de un iframe | No directamente (verificado: 0 coincidencias en el documento principal) | **Sí**, con `frame_selectors` (verificado con iframes del mismo origen y de otro origen) | `probe` lista los iframes y dónde existe el selector |
| La página requiere autenticación | No: habría que guardar credenciales o cookies a mano | **Sí**: perfil persistente e inicio de sesión manual (`python main.py login`) | La página redirige a un *login* o responde 401/403 |
| La página limita la automatización (CAPTCHA, detección de *bots*, límite de peticiones) | **No se debe eludir** | **No se debe eludir** | Respuestas 403/429, desafíos o páginas distintas |

Ante mecanismos que limitan la automatización, el programa **no** intenta eludirlos: no
falsea la identidad del navegador, no resuelve CAPTCHAs y no rota direcciones. Si aparecen, las
observaciones serán `UNKNOWN` o `ERROR` (nunca cambios). Las alternativas legítimas son usar una
API oficial, pedir permiso al responsable del sitio o reducir la frecuencia.

### A.2 Regla de decisión: ¿cuándo basta requests + BeautifulSoup?

`method = "http"` es suficiente **solo si se cumplen todas** estas condiciones:

1. El texto aparece en "Ver código fuente" (lo que envía el servidor), no solo en "Inspeccionar".
2. No está dentro de un iframe (o se observa directamente la URL del iframe).
3. La página no lo oculta o muestra con CSS: sin navegador no se puede saber qué se ve.
4. No hace falta una sesión iniciada.
5. Cada descarga del HTML refleja el estado actual (no hay una caché que lo retrase).

Si falla cualquiera, hace falta `method = "browser"`. Como todavía no se conoce la página, la
configuración de ejemplo usa `browser` (funciona en todos los casos) y el comando
`python main.py probe` comprueba con la página real si `http` sería suficiente. En las pruebas
locales una lectura HTTP tardó unos 3-4 ms y una recarga con el navegador entre 25 y 80 ms; en una
web real dominan la red y el peso de la página. Un navegador consume además bastante más memoria y
CPU que una petición HTTP.

### A.3 Qué necesito de ti

Para configurar y validar el monitor con tu página:

1. **La URL** o, si es privada, **el HTML del elemento y de sus antecesores** (en el
   navegador: clic derecho sobre el texto → Inspeccionar → clic derecho sobre el nodo resaltado →
   Copiar → *Copiar elemento* / *Copy outerHTML*). Elimina los datos personales antes de compartirlo.
2. **Los textos exactos** que quieres detectar y qué estado representa cada uno.
3. **Una captura** de la zona de la página, en cada estado si es posible.
4. Si la página **requiere iniciar sesión**.
5. Si el texto **cambia solo** (sin recargar) o solo al recargar.
6. **La salida de** `python main.py probe --find "texto"` ejecutado en tu Mac (no contiene
   contraseñas; revisa que no incluya datos personales antes de compartirla).

### A.4 Cómo identificar el elemento con las herramientas de desarrollo

**Chrome** (en Safari, activa antes *Safari → Ajustes → Avanzado → Mostrar funciones para
desarrolladores web*):

1. Abre la página y pulsa **⌥⌘I** (Opción + Comando + I).
2. Pulsa **⇧⌘C** y haz clic sobre el texto: el panel *Elements* resalta su nodo HTML.
3. Busca un identificador estable en ese nodo o en un antecesor cercano, por orden de preferencia:
   `id="..."`, `data-testid="..."` u otros `data-*`, `aria-label`, `name`, `role`, etiquetas
   semánticas (`<table>`, `<main>`, `<nav>`...).
4. **Evita** las clases que parecen generadas automáticamente (`css-1x2y3z`, `sc-AbCdE`,
   `_a1b2c3`), las posiciones (`div:nth-child(3)`) y las coordenadas de pantalla: cambian cuando
   la web se actualiza. La opción *Copy selector* de Chrome suele producir selectores posicionales
   frágiles.
5. Comprueba el selector en la pestaña **Console**:
   `document.querySelectorAll('#estado').length` debe devolver `1` (o el número de filas
   esperado).
6. Si el nodo está dentro de un `<iframe>` (aparece bajo `#document`), anota un selector para el
   propio `<iframe>`: va en `frame_selectors`.
7. Pulsa **⌥⌘U** ("Ver código fuente") y busca el texto con ⌘F: si aparece, quizá baste
   `method = "http"`.

Después, ejecuta `python main.py probe --find "texto"`. Lista los elementos que contienen ese texto,
en todos los frames, y propone selectores basados en atributos estables. Junto a cada uno indica
cuántos elementos coinciden en la página real (cuenta comprobada en el navegador, no supuesta).

---

## B. Diseño técnico

### B.1 Arquitectura

```
web_text_monitor/
├── main.py                    Punto de entrada; comprueba la versión de Python (≥ 3.11)
├── config.example.toml        Configuración documentada (copiar a config.toml)
├── config.demo.toml           Configuración para la página de demostración local
├── requirements.txt           playwright, requests, beautifulsoup4 (versiones probadas)
├── requirements-dev.txt       + pytest
├── textmonitor/
│   ├── config.py              Carga y validación del TOML (todos los errores a la vez)
│   ├── models.py              Tipos compartidos (observación, interpretación, evento...)
│   ├── http_extractor.py      Lectura sin navegador: requests + BeautifulSoup
│   ├── browser_manager.py     Lectura con navegador: Playwright, recuperación de fallos, login
│   ├── text_detector.py       Normalización y coincidencias → estado (lógica pura)
│   ├── state_machine.py       Confirmación de cambios y generación de eventos (lógica pura)
│   ├── event_logger.py        Historial CSV: BOM, bloqueo, fsync, cola de reintentos
│   ├── state_store.py         Último estado confirmado (JSON atómico) para reanudar
│   ├── monitor.py             Bucle: reloj monotónico, espera creciente tras errores, parada ordenada
│   ├── console.py             Mensajes de la terminal
│   ├── app_logging.py         Log técnico rotativo
│   ├── probe.py               Diagnóstico de viabilidad de una página concreta
│   ├── demo_server.py         Servidor local de demostración
│   └── cli.py                 Comandos: run, check, probe, login, demo-server
├── poc/                       Pruebas de concepto (sección C)
├── tests/                     121 pruebas automatizadas
├── data/                      events.csv, state.json, perfil del navegador (excluido de git)
└── logs/                      application.log (excluido de git)
```

Respecto a la estructura de referencia: los módulos se agrupan en el paquete `textmonitor/` para
evitar choques de nombre con otras bibliotecas (`config`, `models`...). Además se añaden
`http_extractor.py` (la alternativa sencilla al navegador), `state_store.py` (reanudar),
`probe.py` (viabilidad) y `demo_server.py` (validación sin tocar ninguna web real).
No hay base de datos, interfaz gráfica ni dependencias adicionales.

### B.2 Flujo de datos

```
            cada intervalo (reloj monotónico)
                         │
                         ▼
  ┌───────────────────────────────────────┐   RawObservation
  │ Extractor (HTTP o navegador)          │── status: OK | ELEMENT_NOT_FOUND | ERROR
  │  solo lee; nunca interpreta           │   textos de los elementos, duración, método
  └───────────────────────────────────────┘
                         │
                         ▼
  ┌───────────────────────────────────────┐   Interpretation
  │ TextDetector                          │── VALID (estado + textos presentes)
  │  normaliza, busca los textos,         │   UNKNOWN (no se puede determinar)
  │  aplica las políticas configuradas    │   ERROR (fallo técnico)
  └───────────────────────────────────────┘
                         │
                         ▼
  ┌───────────────────────────────────────┐   StepResult + Event[]
  │ StateMachine                          │── BASELINE, TEXT_APPEARED, TEXT_DISAPPEARED,
  │  compara con el estado confirmado,    │   STATE_CHANGED, UNKNOWN, ERROR, RECOVERED
  │  confirma, evita duplicados           │   (NO_CHANGE no genera eventos)
  └───────────────────────────────────────┘
          │                    │                      │
          ▼                    ▼                      ▼
   CsvEventLogger         StateStore              Console + log técnico
   (events.csv)           (state.json)            (terminal, application.log)
```

La extracción (qué hay en la página) está separada de la interpretación (qué significa) y del
registro (qué se guarda). Por eso el detector y la máquina de estados se prueban con datos
simulados, sin red.

### B.3 Máquina de estados

Variables: **estado confirmado** (o ninguno), **candidato** (estado distinto observado *k* veces
seguidas), **episodio sin lectura** (número de observaciones UNKNOWN/ERROR seguidas) y *N* =
`required_observations`. El estado comparado es el par *(estado, conjunto de textos presentes)*.

```
                      válida = X  (k < N)
                     ┌─────────────┐
                     ▼             │
            ┌──────────────────┐───┘          ┌──────────────────────┐
  inicio ──▶│  SIN LÍNEA BASE  │──────────────▶│   CONFIRMADO = X     │◀─┐ válida = X → NO_CHANGE
            └──────────────────┘ válida = X,   └──────────────────────┘──┘ (descarta el candidato)
                     ▲           N veces:          │              ▲
                     │           BASELINE          │ válida = Y   │ válida = Y, N veces seguidas:
                     │                             ▼              │ TEXT_DISAPPEARED / TEXT_APPEARED /
                     │                  ┌──────────────────────┐  │ STATE_CHANGED; confirmado := Y
                     │                  │ CANDIDATO = Y (k/N)  │──┘
                     │                  └──────────────────────┘
                     │
                     └── tras `rebaseline_after_failures` observaciones no válidas seguidas (opcional)

   UNKNOWN / ERROR en cualquier estado: el estado confirmado NO cambia; se registra una fila al
   empezar el episodio y RECOVERED al terminar. Con unknown_policy = "reset" se descarta el candidato.
```

| Estado actual | Observación | Acción | Eventos |
|---|---|---|---|
| Sin línea base | válida X, *k* < N | candidato X (*k*) | — |
| Sin línea base | válida X, *k* = N | confirmado := X | `BASELINE` |
| Confirmado X | válida X | actualiza "visto por última vez"; descarta el candidato | — (NO_CHANGE) |
| Confirmado X | válida Y ≠ X, *k* < N | candidato Y (*k*); un Y distinto reinicia la cuenta | — |
| Confirmado X | válida Y ≠ X, *k* = N | confirmado := Y | `TEXT_DISAPPEARED`/`TEXT_APPEARED` por texto y `STATE_CHANGED` si cambia el estado (mismo `id_transicion`) |
| Cualquiera | UNKNOWN/ERROR, primera del episodio | conserva el confirmado | `UNKNOWN` o `ERROR` (una fila) |
| Cualquiera | UNKNOWN/ERROR, siguientes | conserva el confirmado | — (solo terminal y log técnico) |
| Episodio en curso | válida | cierra el episodio y continúa como arriba | `RECOVERED` |
| Episodio con *n* ≥ `rebaseline_after_failures` (> 0) | — | descarta confirmado y candidato | la siguiente confirmación es `BASELINE` |

**Primer arranque:** nunca se registra una transición que no se ha observado. La primera
confirmación es `BASELINE`, con `estado_anterior` vacío.

**Reinicio** (`resume_state = true`): se carga el último estado confirmado de `state.json` si
la huella de la configuración coincide (misma URL, selector, textos y reglas). Si al volver el
estado es el mismo, no se escribe nada. Si es otro, se registra el cambio con la ventana
`ultima_obs_estado_anterior_utc` → `primera_obs_estado_nuevo_utc`: el cambio ocurrió en algún
momento de ese intervalo, no necesariamente al reanudar.

### B.4 Políticas de confirmación: ventajas e inconvenientes

| Política | Ventajas | Inconvenientes |
|---|---|---|
| Aceptar tras **1** observación válida (`required_observations = 1`) | Detección más rápida (un intervalo) | Un parpadeo o un renderizado a medias se registra como cambio |
| Exigir **2 o más** observaciones seguidas coherentes (por defecto 2) | Filtra estados que duran menos de un intervalo y lecturas momentáneamente inconsistentes | Confirma (N − 1) intervalos más tarde y no detecta estados más cortos que (N − 1) × intervalo. **No garantiza que el resultado sea correcto**: solo aumenta su consistencia |
| **Ignorar** temporalmente UNKNOWN/ERROR (`unknown_policy = "ignore"`, por defecto) | Un fallo aislado no retrasa la confirmación; un fallo no aporta información en contra | Dos lecturas iguales separadas por un fallo cuentan como seguidas |
| **Reiniciar** la cuenta ante UNKNOWN/ERROR (`"reset"`) | Exige observaciones estrictamente consecutivas | Con fallos frecuentes, la confirmación tarda más o no llega |
| Diferenciar **ausencia** de **fallo de lectura** (siempre activo) | Un error de red nunca se registra como "el texto desapareció" | Requiere decidir qué significa que falte el elemento: `element_missing` |
| **Restablecer la línea base** tras una interrupción (`rebaseline_after_failures > 0`) | Tras un corte largo no se atribuye a ese periodo un cambio cuyo momento se desconoce | El cambio ocurrido durante el corte no aparece como `STATE_CHANGED` (sí se ve comparando los dos `BASELINE`) |
| **Mantener la línea base** tras una interrupción (por defecto) | El cambio se registra con la ventana de tiempo en que pudo ocurrir | La ventana puede ser larga si el corte lo fue |
| **Evitar duplicados** (siempre activo) | Solo se escribe al confirmar un cambio; los fallos, una vez por episodio | — |

### B.5 Eventos

| Tipo | Cuándo | ¿Se guarda en el CSV? |
|---|---|---|
| `TEXT_APPEARED` | Un texto configurado que no estaba pasa a estar (confirmado) | Sí |
| `TEXT_DISAPPEARED` | Un texto que estaba deja de estar (confirmado y con lectura válida) | Sí |
| `STATE_CHANGED` | El estado pasa de uno a otro (incluido `sin_coincidencia`) | Sí |
| `NO_CHANGE` | Lectura válida sin cambios | **Nunca** (solo terminal) |
| `UNKNOWN` | La lectura funcionó pero no permite determinar el estado: elemento ausente, varios elementos con `match_policy = "single"`, estados en conflicto... | Una vez por episodio |
| `ERROR` | Fallo técnico: red, HTTP ≥ 400, tiempo agotado, navegador caído, fallo del detector | Una vez por episodio (detalles en el log) |
| `BASELINE` | Primera confirmación o línea base restablecida | Sí |
| `RECOVERED` | Primera lectura válida tras un episodio UNKNOWN/ERROR | Sí |
| `MONITOR_STARTED` / `MONITOR_STOPPED` | Inicio y fin de cada ejecución, con el motivo | Sí |

Los cuatro últimos son marcadores de cobertura: sin ellos, un periodo sin filas podría significar
tanto "no hubo cambios" como "no se estaba observando". En una sustitución (online → offline) se
escriben tres filas con el mismo `id_transicion`. Si solo quieres una fila por cambio, deja
`record_events` sin `TEXT_APPEARED` ni `TEXT_DISAPPEARED`.

### B.6 Tiempo

* **Intervalo:** `time.monotonic()`, que no salta si cambia la hora del sistema. Las comprobaciones
  siguen una rejilla fija (0, 5, 10... s): la duración de la lectura no se acumula (prueba
  `test_fixed_rate_schedule_does_not_drift`). Si una lectura dura más que el intervalo, se omiten las
  comprobaciones perdidas en lugar de encadenarlas.
* **Marcas de tiempo:** UTC real (`datetime.now(timezone.utc)`), guardadas en ISO 8601 con
  milisegundos y desfase, y convertidas a `America/Lima` (o la zona configurada) con `zoneinfo`.
* **Tras errores:** la espera se duplica (5, 10, 20, 40, 60 s...) hasta `backoff_max_seconds`; con
  `max_consecutive_errors` el programa se detiene tras N errores seguidos.
* **Reposo del Mac:** si entre dos observaciones pasa mucho más tiempo real del previsto, se avisa
  ("No se observó la página durante X s").
* **Limitación:** el intervalo **no** garantiza detectar cambios que empiecen y terminen entre dos
  observaciones. Un estado que dure menos que el intervalo puede no verse nunca.

### B.7 Tratamiento de fallos

| Situación | Clasificación | Efecto |
|---|---|---|
| Sin conexión, DNS, conexión rechazada, tiempo de carga agotado | `ERROR` | Estado conservado; pestaña nueva en el siguiente intento; espera creciente |
| HTTP ≥ 400 (403, 404, 429, 503...) | `ERROR` | Ídem; se vuelve a cargar la URL configurada |
| El navegador o el *driver* se cierran | `ERROR` | Se reinicia Playwright en la siguiente comprobación (probado) |
| La página carga pero el selector no aparece | `UNKNOWN` (o ausencia, si `element_missing = "absent"`) | Estado conservado; la siguiente comprobación recarga la URL |
| Varios elementos con `match_policy = "single"` | `UNKNOWN` | Estado conservado |
| Varios estados a la vez con `multiple_states = "conflict"` | `UNKNOWN` | Estado conservado |
| Excepción en el detector | `ERROR` | Estado conservado; traza en el log |
| No se puede escribir el CSV | — | Filas en cola, reintento en cada ciclo; al salir se copian al log técnico |
| CSV existente con otras columnas o separador | Error de arranque | No se escribe nada en ese archivo |
| Otro monitor usando el mismo CSV | Error de arranque | Archivo `.lock` (`fcntl.flock`) |
| Ctrl+C / SIGTERM / cierre de la terminal | Parada ordenada | Termina la lectura en curso, guarda el estado, escribe `MONITOR_STOPPED` |

### B.8 Seguridad y datos

* Solo se accede a la URL configurada. Los datos se guardan **localmente**; nada se envía a terceros.
* No se guardan contraseñas. Para sitios con sesión, el usuario inicia sesión a mano en una ventana
  del navegador (`python main.py login`) y la sesión queda en `user_data_dir`. Esa carpeta se crea con
  permisos `700`, está excluida de git y equivale a tener la sesión abierta: no la compartas ni la
  sincronices con servicios en la nube. Activa FileVault en el Mac.
* Solo se guarda la parte relevante: el texto coincidente y, opcionalmente, un extracto del elemento
  (`excerpt_max_chars`, 0 para desactivarlo).
* El texto copiado de la página se neutraliza para que Excel no lo ejecute como fórmula (prefijo `'`
  delante de `= + - @`).
* Los errores técnicos nunca se convierten en cambios confirmados, y no se generan eventos que no
  estén respaldados por observaciones.

---

## C. Prueba de concepto

Antes de escribir el sistema se resolvieron las incertidumbres técnicas con dos scripts
independientes de la aplicación (carpeta `poc/`), contra una página local
(`poc/pagina_prueba.html`). Para repetirlos en tu Mac, con el entorno virtual activo:

```bash
python poc/poc_deteccion.py
python poc/poc_ctrl_c.py
```

### C.1 `poc_deteccion.py`: ¿qué ve cada herramienta? (salida real)

```
A. requests + BeautifulSoup (solo HTML estático, sin JavaScript)
----------------------------------------------------------------
HTTP 200, Content-Type='text/html'
  requests adivina la codificación: 'ISO-8859-1' -> 'Cargandoâ\x80¦'
  BeautifulSoup con los bytes detecta: 'utf-8'
  #estado-estatico   coincidencias=1 texto=['online']
  #estado-js         coincidencias=1 texto=['Cargando…']
  #oculto            coincidencias=1 texto=['offline']
  #padre             coincidencias=1 texto=['visible hijo-oculto']
  #invisible         coincidencias=1 texto=['texto-invisible']
  #estado-marco      coincidencias=0 texto=[]

B. Playwright + Chromium (después de ejecutar JavaScript)
---------------------------------------------------------
HTTP 200
  #estado-estatico   visible=True  innerText='online'                   textContent='online'
  #estado-js         visible=True  innerText='online'                   textContent='online'
  #oculto            visible=False innerText='offline'                  textContent='offline'
  #padre             visible=True  innerText='visible'                  textContent='visible hijo-oculto'
  #invisible         visible=False innerText=''                         textContent='texto-invisible'

C. Cambios dinámicos: 5 lecturas de #estado-js sin recargar, cada 0,7 s
-----------------------------------------------------------------------
  lectura 1: 'online'
  lectura 2: 'online'
  lectura 3: 'online'
  lectura 4: 'offline'
  lectura 5: 'offline'

D. Iframes (frame_locator)
--------------------------
  iframe #marco          -> 'online dentro del iframe'
  iframe #marco-externo  -> 'online dentro del iframe'
  frames de la página: ['http://localhost:35775/pagina_prueba.html', 'http://localhost:35775/marco.html', 'http://127.0.0.1:35775/marco.html']
  '#estado-marco' buscado solo en el documento principal: 0 coincidencias

E. Elemento inexistente / error de conexión / HTTP 503
------------------------------------------------------
  elemento inexistente -> TimeoutError: Locator.wait_for: Timeout 1500ms exceeded.
  HTTP 503 (página nueva)        -> sin excepción; response.status = 503
  puerto cerrado (página nueva)  -> Error: Page.goto: net::ERR_CONNECTION_REFUSED at http://127.0.0.1:44833/
  HTTP 503 tras el fallo, misma página -> Error: Page.goto: Navigation to "http://localhost:35775/error503" is interrupted by another navigation to "chrome-error://chromewebdata/"
```

### C.2 `poc_ctrl_c.py`: ¿qué le pasa a Playwright con Ctrl+C? (salida real, extracto)

Ctrl+C envía SIGINT a todo el grupo de procesos: Python, el *driver* de Playwright y el navegador.
El script lo reproduce con `os.killpg()`:

```
=== Variante: por_defecto ===
hijo: SIGINT recibido; termino la lectura en curso
hijo: ERROR al leer -> TargetClosedError: Locator.inner_text: Target page, context or browser has been closed
hijo: navegador cerrado ordenadamente

=== Variante: sin_senales ===
hijo: SIGINT recibido; termino la lectura en curso
hijo: lectura después de SIGINT OK -> 'online'
hijo: navegador cerrado ordenadamente
```

### C.3 Conclusiones y decisiones de diseño derivadas

| Hallazgo (verificado) | Decisión |
|---|---|
| requests no ve el texto escrito por JavaScript (`Cargando…`) ni el contenido de los iframes | Dos extractores; `probe` decide con la página real |
| Si el servidor no declara el *charset*, requests supone ISO-8859-1 y estropea las tildes | Se pasan los **bytes** a BeautifulSoup, que respeta `<meta charset>` |
| `innerText` de un elemento con `display:none` **devuelve su texto** (`'offline'`) | Se comprueba la visibilidad en la misma llamada; un elemento oculto cuenta como texto vacío (`text_source = "visible"`) |
| Un hijo oculto se excluye de `innerText`, pero no de `textContent` | `text_source` configurable; `visible` por defecto |
| El texto puede cambiar sin recargar; una lectura sin recargar lo ve | `reload_each_check` configurable |
| `frame_locator` funciona con iframes del mismo origen y de otro origen | `frame_selectors` |
| Elemento inexistente → `TimeoutError`; conexión rechazada → `Error`; HTTP 503 → respuesta normal con `status = 503` | Tres caminos distintos: `ELEMENT_NOT_FOUND` (→ UNKNOWN), `ERROR` y `ERROR` con código HTTP |
| Tras una navegación fallida, reutilizar la pestaña provoca un error espurio | Tras cualquier error se descarta la pestaña y se abre otra |
| Con las opciones por defecto, Ctrl+C cierra el navegador a mitad de la lectura | `handle_sigint/handle_sigterm/handle_sighup = False` y un manejador propio que solo activa una bandera |

Hallazgo posterior, durante las pruebas de integración: si el elemento existe con un marcador
(`Cargando…`) antes de que JavaScript escriba el valor, una recarga seguida de una lectura inmediata
lee el marcador. Se añadió `settle_seconds` y `probe` lo detecta ("El texto cambió en los 2 s
siguientes a la carga"). Para estas páginas se recomienda `reload_each_check = false`.

### C.4 Diagnóstico de la página de demostración con `probe` (salida real, extracto)

```
1. Sin navegador: requests + BeautifulSoup (HTML tal como lo envía el servidor)
  HTTP 200 en 3 ms; Content-Type 'text/html; charset=utf-8'; 1014 bytes
  Elementos que coinciden con '#estado-js': 1
    1. 'Cargando…'
  Interpretación: estado 'sin_coincidencia'; textos encontrados: ninguno

2. Con navegador: Playwright + Chromium (después de ejecutar JavaScript)
  HTTP 200 en 25 ms; título 'Demo del monitor de textos'
  Elementos que coinciden con '#estado-js': 1
    1. visible=True texto visible='Cargando…'
  Interpretación: estado 'sin_coincidencia'; textos encontrados: ninguno
  El texto cambió en los 2 s siguientes a la carga: 'Cargando…' -> 'online'
  Interpretación 2 s después: estado 'online'; textos encontrados: online

Conclusión
  - El HTML estático y la página renderizada no dicen lo mismo (JavaScript o CSS cambian el texto): usa method = "browser".
  - El texto cambia justo después de cargar (marcador de carga o datos que llegan por JavaScript). Con reload_each_check = true usa settle_seconds (p. ej. 2) o, mejor, reload_each_check = false.
```

Con `--find online`, el mismo comando encontró los tres elementos de la demo y comprobó en la
página que `#estado`, `span[data-testid="estado-servicio"]`, `#estado-js` y `#estado-marco`
(este último dentro del iframe) identifican un único elemento cada uno.
