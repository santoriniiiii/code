"""Integración con un navegador real (Playwright + Chromium) contra páginas locales.

Se omiten automáticamente si Playwright o Chromium no están instalados.
Ninguna prueba accede a internet: todo ocurre en 127.0.0.1 o en archivos locales.
"""

from __future__ import annotations

import csv
import io
import os
import time
from pathlib import Path

import pytest
from conftest import make_config

from textmonitor.demo_server import ERROR_STATE, DemoState, make_server, start_in_thread
from textmonitor.models import ObservationKind, ReadStatus
from textmonitor.text_detector import TextDetector

pytestmark = pytest.mark.browser


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:
        return False


if not _chromium_available():
    pytest.skip("Playwright/Chromium no disponible", allow_module_level=True)

from textmonitor.browser_manager import BrowserManager, BrowserStartError  # noqa: E402


@pytest.fixture
def demo():
    state = DemoState()
    state.set("online")
    server, url = start_in_thread(state)
    yield state, url, server
    server.shutdown()
    server.server_close()


def manager(url: str, **extraction) -> tuple[BrowserManager, TextDetector]:
    config = make_config(page={"url": url}, extraction={"selector": "#estado", "element_timeout_seconds": 3,
                                                         **extraction})
    bm = BrowserManager(config)
    bm.start()
    return bm, TextDetector(config)


def state_of(bm: BrowserManager, detector: TextDetector) -> str | None:
    interp = detector.interpret(bm.observe())
    return interp.snapshot.state if interp.kind is ObservationKind.VALID else interp.kind.value


def test_reload_each_check_sees_server_changes(demo):
    state, url, _ = demo
    bm, det = manager(url + "/")
    try:
        assert state_of(bm, det) == "online"
        state.set("offline")
        assert state_of(bm, det) == "offline"
    finally:
        bm.close()


def test_without_reload_reads_live_javascript_updates(demo):
    state, url, _ = demo
    bm, det = manager(url + "/", reload_each_check=False)
    try:
        assert state_of(bm, det) == "online"
        state.set("offline")
        time.sleep(1.6)  # la página consulta /api/estado cada segundo
        assert state_of(bm, det) == "offline"
    finally:
        bm.close()


def test_placeholder_is_read_unless_settle_time_is_configured(demo):
    _, url, _ = demo
    bm, _ = manager(url + "/", selector="#estado-js")
    try:
        assert bm.observe().texts == ("Cargando…",)  # el elemento existe antes de que JavaScript lo rellene
    finally:
        bm.close()
    bm, det = manager(url + "/", selector="#estado-js", settle_seconds=1.0)
    try:
        assert state_of(bm, det) == "online"
    finally:
        bm.close()


def test_text_inside_iframe(demo):
    _, url, _ = demo
    bm, det = manager(url + "/", selector="#estado-marco", frame_selectors=["#marco"])
    try:
        assert state_of(bm, det) == "online"
    finally:
        bm.close()
    bm, det = manager(url + "/", selector="#estado-marco", element_timeout_seconds=0.5)
    try:
        assert bm.observe().status is ReadStatus.ELEMENT_NOT_FOUND  # sin frame_selectors no se ve
    finally:
        bm.close()


def test_hidden_text_only_counts_with_text_source_all(tmp_path):
    page = tmp_path / "pagina.html"
    page.write_text(
        '<!doctype html><meta charset="utf-8">'
        '<div id="estado" style="display:none">offline</div>'
        '<div id="padre">online <span style="display:none">offline</span></div>',
        encoding="utf-8",
    )
    url = page.as_uri()
    bm, det = manager(url)
    try:
        assert bm.observe().texts == ("",)  # innerText devolvería "offline" aunque no se ve
        assert state_of(bm, det) == "sin_coincidencia"
    finally:
        bm.close()
    bm, det = manager(url, text_source="all")
    try:
        assert state_of(bm, det) == "offline"
    finally:
        bm.close()
    bm, det = manager(url, selector="#padre")
    try:
        assert state_of(bm, det) == "online"  # el hijo oculto no provoca un conflicto
    finally:
        bm.close()


def test_missing_element_is_not_an_error(demo):
    _, url, _ = demo
    bm, _ = manager(url + "/", selector="#no-existe", element_timeout_seconds=0.5)
    try:
        observation = bm.observe()
        assert observation.status is ReadStatus.ELEMENT_NOT_FOUND
        assert "no apareció" in observation.detail
    finally:
        bm.close()


def test_http_503_is_error_and_reading_recovers(demo):
    state, url, _ = demo
    bm, det = manager(url + "/")
    try:
        assert state_of(bm, det) == "online"
        state.set(ERROR_STATE)
        observation = bm.observe()
        assert observation.status is ReadStatus.ERROR and observation.http_status == 503
        state.set("offline")
        assert state_of(bm, det) == "offline"
    finally:
        bm.close()


def test_server_down_and_back(demo):
    state, url, server = demo
    port = server.server_address[1]
    bm, det = manager(url + "/")
    try:
        assert state_of(bm, det) == "online"
        server.shutdown()
        server.server_close()
        observation = bm.observe()
        assert observation.status is ReadStatus.ERROR
        assert "ERR_CONNECTION_REFUSED" in observation.detail
        restarted = make_server(state, "127.0.0.1", port)
        import threading

        threading.Thread(target=restarted.serve_forever, daemon=True).start()
        try:
            assert state_of(bm, det) == "online"  # pestaña nueva tras el fallo; sin errores espurios
        finally:
            restarted.shutdown()
            restarted.server_close()
    finally:
        bm.close()


def test_browser_crash_is_recovered_by_relaunching(demo):
    _, url, _ = demo
    bm, det = manager(url + "/")
    try:
        assert state_of(bm, det) == "online"
        bm._browser.close()  # simula que el navegador se cierra o se bloquea
        assert state_of(bm, det) == "online"
    finally:
        bm.close()


def test_persistent_profile_keeps_cookies_between_runs(demo, tmp_path):
    _, url, _ = demo
    profile = tmp_path / "perfil"
    config = make_config(page={"url": url + "/"}, extraction={"selector": "#estado"},
                         browser={"user_data_dir": str(profile)})
    first = BrowserManager(config)
    first.start()
    try:
        assert first.observe().status is ReadStatus.OK
        first._page.evaluate("document.cookie = 'sesion=abc123; max-age=3600; path=/'")
        with pytest.raises(BrowserStartError):
            BrowserManager(config).start()  # el mismo perfil no se abre dos veces
    finally:
        first.close()
    assert oct(profile.stat().st_mode & 0o777) == "0o700"
    second = BrowserManager(config)
    second.start()
    try:
        assert second.observe().status is ReadStatus.OK
        assert "sesion=abc123" in second._page.evaluate("document.cookie")
    finally:
        second.close()


def test_missing_executable_gives_clear_message():
    config = make_config(browser={"executable_path": "/no/existe/chrome"})
    with pytest.raises(BrowserStartError, match="executable_path"):
        BrowserManager(config).start()


def test_probe_on_demo_page(demo):
    from textmonitor.probe import run_probe

    _, url, _ = demo
    out = io.StringIO()
    config = make_config(page={"url": url + "/"}, extraction={"selector": "#estado-js"})
    run_probe(config, out, find_text="online", samples=1)
    text = out.getvalue()
    assert "Elementos que coinciden con '#estado-js': 1" in text
    assert "'Cargando…'" in text  # lo que ve requests
    assert "El texto cambió en los 2 s siguientes a la carga" in text
    assert "selector candidato: #estado  -> único" in text
    assert "settle_seconds" in text  # recomendación en la conclusión
    assert "Interpretación 2 s después: estado 'online'" in text
    assert 'method = "http" sería suficiente' not in text  # requests solo ve "Cargando…"
    assert "no dicen lo mismo" in text


@pytest.mark.skipif(not hasattr(os, "killpg"), reason="requiere señales POSIX (macOS/Linux)")
def test_full_program_browser_mode_stops_cleanly_on_sigint(demo, tmp_path):
    from test_integration_http import run_and_interrupt, write_config

    _, url, _ = demo
    config = write_config(tmp_path, url + "/", method="browser")
    code, output = run_and_interrupt(config, "Sin cambios")
    assert code == 0, output
    assert "Monitor detenido (detenido por el usuario (Ctrl+C))" in output
    with (tmp_path / "events.csv").open(encoding="utf-8-sig", newline="") as fh:
        types = [r["tipo_evento"] for r in csv.DictReader(fh)]
    assert types == ["MONITOR_STARTED", "BASELINE", "MONITOR_STOPPED"]  # sin ERROR provocado por Ctrl+C
    assert Path(tmp_path / "app.log").exists()
