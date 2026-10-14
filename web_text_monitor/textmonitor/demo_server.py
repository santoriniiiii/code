"""Servidor web local de demostración (solo 127.0.0.1).

Permite validar el monitor de principio a fin sin tocar ninguna web real:
el estado alterna entre "online" y "offline" (y, opcionalmente, una fase en
la que el servidor responde HTTP 503). La página contiene:

  * #estado       -> escrito por el servidor en el HTML y actualizado por JavaScript cada segundo.
  * #estado-js    -> solo lo escribe JavaScript (requests + BeautifulSoup no lo ve).
  * iframe #marco -> contiene #estado-marco.

Uso: python main.py demo-server   (y en otra terminal: python main.py --config config.demo.toml run)
"""

from __future__ import annotations

import html
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import urlparse

ERROR_STATE = "__error__"

_SCRIPT = """
<script>
  async function actualizar() {
    try {
      const r = await fetch('/api/estado', {cache: 'no-store'});
      if (!r.ok) return;
      const datos = await r.json();
      for (const id of IDS) {
        const el = document.getElementById(id);
        if (el) el.textContent = datos.estado;
      }
    } catch (e) { /* servidor caído: se deja el último valor */ }
  }
  setTimeout(actualizar, 300);
  setInterval(actualizar, 1000);
</script>
"""

_PAGE = """<!doctype html>
<html lang="es">
<head><meta charset="utf-8"><title>Demo del monitor de textos</title>
<style>body{{font-family:-apple-system,system-ui,sans-serif;margin:2rem}}#estado{{font-weight:bold}}</style>
</head>
<body>
<h1>Servicio de demostración</h1>
<p>Estado del servicio: <span id="estado" data-testid="estado-servicio">{estado}</span></p>
<p>Estado escrito solo por JavaScript: <span id="estado-js">Cargando…</span></p>
<iframe id="marco" title="Panel embebido" src="/marco" width="400" height="80"></iframe>
{script}
</body>
</html>
"""

_FRAME = """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Panel</title></head>
<body><p>Panel embebido: <span id="estado-marco">{estado}</span></p>{script}</body></html>
"""


class DemoState:
    """Estado actual del servicio simulado: un ciclo automático o un valor fijo."""

    def __init__(self, cycle: list[tuple[str, float]] | None = None, clock: Callable[[], float] = time.monotonic):
        self._cycle = cycle or [("online", 30.0), ("offline", 30.0)]
        self._clock = clock
        self._t0 = clock()
        self._override: str | None = None
        self._lock = threading.Lock()

    def set(self, value: str | None) -> None:
        """Fija un estado (o None para volver al ciclo automático)."""
        with self._lock:
            self._override = value

    def current(self) -> str:
        with self._lock:
            if self._override is not None:
                return self._override
        total = sum(seconds for _, seconds in self._cycle)
        position = (self._clock() - self._t0) % total
        for value, seconds in self._cycle:
            if position < seconds:
                return value
            position -= seconds
        return self._cycle[-1][0]


class _Handler(BaseHTTPRequestHandler):
    server_version = "DemoMonitor/1.0"

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        state = self.server.demo_state.current()  # type: ignore[attr-defined]
        if state == ERROR_STATE and path in ("/", "/estatico", "/api/estado", "/marco"):
            self._send(503, "text/plain; charset=utf-8", "Servicio no disponible (simulado)")
            return
        if path == "/":
            body = _PAGE.format(estado=html.escape(state),
                                script=_SCRIPT.replace("IDS", '["estado", "estado-js"]'))
            self._send(200, "text/html; charset=utf-8", body)
        elif path == "/marco":
            self._send(200, "text/html; charset=utf-8",
                       _FRAME.format(estado=html.escape(state), script=_SCRIPT.replace("IDS", '["estado-marco"]')))
        elif path == "/api/estado":
            self._send(200, "application/json", json.dumps({"estado": state}))
        else:
            self._send(404, "text/plain; charset=utf-8", "No encontrado")

    def _send(self, status: int, content_type: str, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args) -> None:
        pass


def make_server(state: DemoState, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _Handler)
    server.demo_state = state  # type: ignore[attr-defined]
    server.daemon_threads = True
    return server


def start_in_thread(state: DemoState, host: str = "127.0.0.1", port: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Arranca el servidor en segundo plano (para pruebas). Devuelve (servidor, url_base)."""
    server = make_server(state, host, port)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://{host}:{server.server_address[1]}"


def serve(host: str, port: int, period: float, with_errors: bool) -> int:
    cycle = [("online", period), ("offline", period)]
    if with_errors:
        cycle.append((ERROR_STATE, max(period / 2, 1.0)))
    server = make_server(DemoState(cycle), host, port)
    phases = ", ".join(f"{'HTTP 503' if v == ERROR_STATE else v} {s:g} s" for v, s in cycle)
    print(f"Servidor de demostración en http://{host}:{port}/  (ciclo: {phases})")
    print("Pulsa Ctrl+C para detenerlo.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    print("Servidor de demostración detenido.")
    return 0
