"""Integración sin navegador: requests + BeautifulSoup contra el servidor de demostración local.

También ejecuta el programa completo (`main.py run`) en un subproceso y lo detiene
con SIGINT, como haría Ctrl+C en la terminal.
"""

from __future__ import annotations

import csv
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest
from conftest import make_config

from textmonitor.demo_server import ERROR_STATE, DemoState, start_in_thread
from textmonitor.http_extractor import HttpExtractor, charset_from_headers
from textmonitor.models import ReadStatus

PROJECT = Path(__file__).resolve().parent.parent


@pytest.fixture
def demo():
    state = DemoState()
    state.set("online")
    server, url = start_in_thread(state)
    yield state, url
    server.shutdown()
    server.server_close()


def extractor(url: str, selector: str = "#estado") -> HttpExtractor:
    return HttpExtractor(make_config(page={"url": url}, extraction={"method": "http", "selector": selector}))


def test_reads_server_rendered_text(demo):
    state, url = demo
    ex = extractor(url + "/")
    first = ex.observe()
    assert first.status is ReadStatus.OK and first.texts == ("online",)
    state.set("offline")
    assert ex.observe().texts == ("offline",)  # cada lectura descarga la página de nuevo


def test_javascript_text_is_not_visible_without_browser_and_accents_survive(demo):
    _, url = demo
    observation = extractor(url + "/", "#estado-js").observe()
    assert observation.texts == ("Cargando…",)  # solo el marcador: el valor lo escribe JavaScript


def test_missing_element(demo):
    _, url = demo
    observation = extractor(url + "/", "#no-existe").observe()
    assert observation.status is ReadStatus.ELEMENT_NOT_FOUND


def test_http_error_status_is_error(demo):
    state, url = demo
    state.set(ERROR_STATE)
    observation = extractor(url + "/").observe()
    assert observation.status is ReadStatus.ERROR
    assert observation.http_status == 503


def test_connection_refused_is_error():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    observation = extractor(f"http://127.0.0.1:{port}/").observe()
    assert observation.status is ReadStatus.ERROR
    assert "no se pudo conectar" in observation.detail


def test_charset_from_headers():
    assert charset_from_headers("text/html; charset=ISO-8859-1") == "ISO-8859-1"
    assert charset_from_headers("text/html") is None
    assert charset_from_headers(None) is None


def write_config(tmp_path: Path, url: str, method: str = "http") -> Path:
    config = tmp_path / "config.toml"
    config.write_text(f"""
[page]
url = "{url}"
label = "Demo"
[extraction]
method = "{method}"
selector = "#estado"
element_timeout_seconds = 5
[[targets]]
id = "online"
text = "online"
mode = "word"
[[targets]]
id = "offline"
text = "offline"
mode = "word"
[confirmation]
required_observations = 1
[schedule]
interval_seconds = 1
[output]
csv_path = "events.csv"
state_path = "state.json"
log_path = "app.log"
""", encoding="utf-8")
    return config


def run_and_interrupt(config: Path, wait_for: str, timeout: float = 60.0) -> tuple[int, str]:
    """Ejecuta main.py run en su propio grupo de procesos y le envía SIGINT (como Ctrl+C)."""
    process = subprocess.Popen(
        [sys.executable, str(PROJECT / "main.py"), "--config", str(config), "run"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, start_new_session=True,
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
    )
    output = []
    deadline = time.monotonic() + timeout
    assert process.stdout is not None
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if not line:
            break
        output.append(line)
        if wait_for in line:
            break
    os.killpg(process.pid, signal.SIGINT)
    try:
        rest, _ = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        rest, _ = process.communicate()
    return process.returncode, "".join(output) + rest


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="requiere señales POSIX (macOS/Linux)")
def test_full_program_http_mode_stops_cleanly_on_sigint(demo, tmp_path):
    state, url = demo
    config = write_config(tmp_path, url + "/")
    code, output = run_and_interrupt(config, "Línea base establecida")
    assert code == 0, output
    assert "Monitor detenido (detenido por el usuario (Ctrl+C))" in output
    with (tmp_path / "events.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
    types = [r["tipo_evento"] for r in rows]
    assert types[0] == "MONITOR_STARTED" and types[-1] == "MONITOR_STOPPED"
    assert "BASELINE" in types
    assert (tmp_path / "events.csv").read_bytes().endswith(b"\r\n")
