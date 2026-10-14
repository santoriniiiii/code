"""Prueba de concepto: ¿qué le ocurre a Playwright cuando se pulsa Ctrl+C?

En una terminal, Ctrl+C envía SIGINT a TODO el grupo de procesos en primer
plano: Python, el "driver" de Playwright (un proceso Node.js) y el navegador.
Este script reproduce esa situación sin terminal: lanza un proceso hijo en su
propio grupo, espera a que esté leyendo una página y envía SIGINT al grupo
completo con os.killpg(). Después comprueba si el hijo pudo seguir usando
Playwright y cerrar el navegador de forma ordenada.

Variantes:
  * por_defecto        -> launch() con las opciones por defecto.
  * sin_senales        -> launch(handle_sigint=False, handle_sigterm=False, handle_sighup=False).
  * driver_ignora      -> igual que sin_senales y, además, SIGINT ignorado (SIG_IGN)
                          mientras se crea el driver, para que lo herede.

Uso: python poc/poc_ctrl_c.py   (solo funciona en macOS/Linux)
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time

HIJO = r"""
import signal, sys, time
from playwright.sync_api import sync_playwright

variante = sys.argv[1]
parar = False

def al_recibir_sigint(signum, frame):
    global parar
    parar = True
    print("hijo: SIGINT recibido; termino la lectura en curso", flush=True)

if variante == "driver_ignora":
    signal.signal(signal.SIGINT, signal.SIG_IGN)
pw = sync_playwright().start()
opciones = {} if variante == "por_defecto" else dict(handle_sigint=False, handle_sigterm=False, handle_sighup=False)
navegador = pw.chromium.launch(headless=True, **opciones)
signal.signal(signal.SIGINT, al_recibir_sigint)
pagina = navegador.new_page()
pagina.set_content("<p id='estado'>online</p>")
print("hijo: listo", flush=True)
lecturas = 0
try:
    while not parar:
        pagina.locator("#estado").inner_text()
        lecturas += 1
        time.sleep(0.05)
    # Tras Ctrl+C: ¿sigue funcionando Playwright para una última lectura?
    texto = pagina.locator("#estado").inner_text(timeout=3000)
    print(f"hijo: lectura después de SIGINT OK -> {texto!r}", flush=True)
except Exception as exc:
    print(f"hijo: ERROR al leer -> {type(exc).__name__}: {str(exc).splitlines()[0]}", flush=True)
try:
    navegador.close()
    pw.stop()
    print("hijo: navegador cerrado ordenadamente", flush=True)
except Exception as exc:
    print(f"hijo: ERROR al cerrar -> {type(exc).__name__}: {str(exc).splitlines()[0]}", flush=True)
"""


def probar(variante: str) -> None:
    print(f"\n=== Variante: {variante} ===")
    proceso = subprocess.Popen(
        [sys.executable, "-c", HIJO, variante],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,  # grupo de procesos propio, como una terminal
    )
    assert proceso.stdout is not None
    linea = proceso.stdout.readline()
    print(linea.rstrip())
    time.sleep(0.5)
    os.killpg(proceso.pid, signal.SIGINT)  # lo que hace Ctrl+C en la terminal
    try:
        salida, _ = proceso.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        os.killpg(proceso.pid, signal.SIGKILL)
        salida, _ = proceso.communicate()
        print("(el hijo no terminó en 20 s y se forzó su cierre)")
    print(salida.rstrip())
    print(f"código de salida del hijo: {proceso.returncode}")


if __name__ == "__main__":
    for variante in ("por_defecto", "sin_senales", "driver_ignora"):
        probar(variante)
