"""Prueba de concepto: ¿qué herramienta ve qué texto?

Sirve `pagina_prueba.html` en un servidor local y compara lo que obtienen
requests + BeautifulSoup (HTML estático) y Playwright (navegador real) en
los casos que más afectan al diseño del monitor:

  1. Texto presente directamente en el HTML.
  2. Texto escrito por JavaScript que además cambia sin recargar la página.
  3. Elemento oculto con display:none.
  4. Elemento visible con un hijo oculto.
  5. Elemento con visibility:hidden.
  6. Iframe del mismo origen.
  7. Iframe de otro origen.
  8. Elemento inexistente frente a error de conexión frente a HTTP 503.

Uso (desde la carpeta web_text_monitor, con el entorno virtual activo):

    python poc/poc_deteccion.py

No accede a internet: todo ocurre en 127.0.0.1 / localhost.
"""

from __future__ import annotations

import functools
import http.server
import socket
import threading
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

POC_DIR = Path(__file__).resolve().parent

# Lee, en una sola llamada, el texto visible, el texto completo y la visibilidad
# de todos los elementos que coinciden con el selector.
LEER_ELEMENTOS_JS = """
(elementos) => elementos.map((e) => {
  const estilo = window.getComputedStyle(e);
  const caja = e.getBoundingClientRect();
  return {
    innerText: e.innerText,
    textContent: e.textContent,
    visible: estilo.visibility === 'visible' && caja.width > 0 && caja.height > 0,
  };
})
"""


class Manejador(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (nombre impuesto por http.server)
        if self.path == "/error503":
            self.send_error(503, "Servicio no disponible (simulado)")
            return
        super().do_GET()

    def log_message(self, *args):  # silencia el registro por petición
        pass


def iniciar_servidor() -> http.server.ThreadingHTTPServer:
    manejador = functools.partial(Manejador, directory=str(POC_DIR))
    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), manejador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor


def puerto_libre() -> int:
    """Devuelve un puerto local en el que no escucha nadie."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def primera_linea(exc: Exception) -> str:
    return str(exc).splitlines()[0]


def titulo(texto: str) -> None:
    print()
    print(texto)
    print("-" * len(texto))


def prueba_http(url: str, selectores: list[str]) -> None:
    titulo("A. requests + BeautifulSoup (solo HTML estático, sin JavaScript)")
    respuesta = requests.get(url, timeout=10)
    print(f"HTTP {respuesta.status_code}, Content-Type={respuesta.headers.get('Content-Type')!r}")
    print(f"  requests adivina la codificación: {respuesta.encoding!r} -> {respuesta.text[respuesta.text.find('Cargando'):][:11]!r}")
    # Se entregan los bytes a BeautifulSoup para que use <meta charset="utf-8">.
    sopa = BeautifulSoup(respuesta.content, "html.parser")
    print(f"  BeautifulSoup con los bytes detecta: {sopa.original_encoding!r}")
    for selector in selectores:
        elementos = sopa.select(selector)
        textos = [" ".join(e.get_text(" ").split()) for e in elementos]
        print(f"  {selector:<18} coincidencias={len(elementos)} texto={textos}")


def prueba_navegador(url: str, selectores: list[str]) -> None:
    with sync_playwright() as p:
        navegador = p.chromium.launch(headless=True)
        pagina = navegador.new_page()
        respuesta = pagina.goto(url, wait_until="load", timeout=15_000)
        print()
        titulo("B. Playwright + Chromium (después de ejecutar JavaScript)")
        print(f"HTTP {respuesta.status if respuesta else 'sin respuesta'}")
        pagina.locator("#estado-js").filter(has_not_text="Cargando").wait_for(timeout=5_000)
        for selector in selectores:
            datos = pagina.locator(selector).evaluate_all(LEER_ELEMENTOS_JS)
            for d in datos:
                print(
                    f"  {selector:<18} visible={str(d['visible']):<5} "
                    f"innerText={d['innerText']!r:<26} textContent={d['textContent']!r}"
                )

        titulo("C. Cambios dinámicos: 5 lecturas de #estado-js sin recargar, cada 0,7 s")
        for n in range(5):
            texto = pagina.locator("#estado-js").inner_text()
            print(f"  lectura {n + 1}: {texto!r}")
            time.sleep(0.7)

        titulo("D. Iframes (frame_locator)")
        for marco in ("#marco", "#marco-externo"):
            texto = pagina.frame_locator(marco).locator("#estado-marco").inner_text(timeout=5_000)
            print(f"  iframe {marco:<15} -> {texto!r}")
        print(f"  frames de la página: {[f.url for f in pagina.frames]}")
        en_principal = pagina.locator("#estado-marco").count()
        print(f"  '#estado-marco' buscado solo en el documento principal: {en_principal} coincidencias")

        titulo("E. Elemento inexistente / error de conexión / HTTP 503")
        try:
            pagina.locator("#no-existe").wait_for(state="attached", timeout=1_500)
        except PlaywrightTimeoutError as exc:
            print(f"  elemento inexistente -> {type(exc).__name__}: {primera_linea(exc)}")
        url_503 = url.rsplit("/", 1)[0] + "/error503"
        url_cerrada = f"http://127.0.0.1:{puerto_libre()}/"

        pagina_nueva = navegador.new_page()
        respuesta = pagina_nueva.goto(url_503, timeout=5_000)
        print(f"  HTTP 503 (página nueva)        -> sin excepción; response.status = {respuesta.status}")
        pagina_nueva.close()

        pagina_nueva = navegador.new_page()
        try:
            pagina_nueva.goto(url_cerrada, timeout=5_000)
        except PlaywrightError as exc:
            print(f"  puerto cerrado (página nueva)  -> {type(exc).__name__}: {primera_linea(exc)}")
        try:
            respuesta = pagina_nueva.goto(url_503, timeout=5_000)
            print(f"  HTTP 503 tras el fallo, misma página -> response.status = {respuesta.status}")
        except PlaywrightError as exc:
            print(f"  HTTP 503 tras el fallo, misma página -> {type(exc).__name__}: {primera_linea(exc)}")
        pagina_nueva.close()
        navegador.close()


def main() -> None:
    servidor = iniciar_servidor()
    puerto = servidor.server_address[1]
    url = f"http://localhost:{puerto}/pagina_prueba.html"
    print(f"Página de prueba: {url}")
    selectores = ["#estado-estatico", "#estado-js", "#oculto", "#padre", "#invisible", "#estado-marco"]
    try:
        prueba_http(url, selectores)
        prueba_navegador(url, selectores)
    finally:
        servidor.shutdown()


if __name__ == "__main__":
    main()
