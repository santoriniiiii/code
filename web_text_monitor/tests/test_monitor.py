"""Pruebas del bucle principal con un reloj falso y un extractor simulado."""

from __future__ import annotations

import csv
import io
import os
from datetime import timedelta

from conftest import T0, FakeClock, ScriptedExtractor, build_machine, error, make_config

from textmonitor.console import Console
from textmonitor.event_logger import CsvEventLogger
from textmonitor.monitor import EXIT_OK, EXIT_TOO_MANY_ERRORS, Monitor
from textmonitor.state_store import StateStore
from textmonitor.text_detector import TextDetector


class Harness:
    def __init__(self, tmp_path, script, *, max_cycles=None, duration_s=0.2, on_observe=None, wall_start=T0,
                 session="s1", **sections):
        self.config = make_config(tmp_path, **sections)
        self.clock = FakeClock()
        self.out = io.StringIO()
        self.waits: list[float] = []
        self.max_cycles = max_cycles if max_cycles is not None else len(script)
        self.extractor = ScriptedExtractor(script, self.clock, wall_start=wall_start, duration_s=duration_s,
                                           on_observe=on_observe)
        self.logger = CsvEventLogger(
            self.config.output.csv_path, timezone=self.config.output.timezone, page_label="Prueba",
            url=self.config.page.url, selector="#estado", session_id=session,
            record_events=self.config.output.record_events,
        )
        self.logger.open()
        self.monitor = Monitor(
            self.config, self.extractor, TextDetector(self.config), build_machine(self.config), self.logger,
            StateStore(self.config.output.state_path, self.config.fingerprint()),
            Console(self.config.tz, "normal", self.out),
            clock=self.clock, now_utc=self.extractor.wall_now, wait=self._wait,
        )

    def _wait(self, seconds: float) -> bool:
        self.waits.append(round(seconds, 6))
        if self.extractor.calls >= self.max_cycles:
            self.monitor.request_stop("fin del guion de la prueba")
        self.clock.advance(seconds)
        return self.monitor.stop_requested

    def run(self) -> int:
        return self.monitor.run()

    def rows(self) -> list[dict[str, str]]:
        with self.config.output.csv_path.open(encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))

    def types(self) -> list[str]:
        return [r["tipo_evento"] for r in self.rows()]


def test_session_markers_and_basic_cycle(tmp_path):
    h = Harness(tmp_path, ["online", "online", "offline"])
    assert h.run() == EXIT_OK
    assert h.types() == ["MONITOR_STARTED", "BASELINE", "TEXT_DISAPPEARED", "TEXT_APPEARED",
                         "STATE_CHANGED", "MONITOR_STOPPED"]
    assert h.extractor.started and h.extractor.closed
    text = h.out.getvalue()
    assert "[10:00:00] Línea base establecida: online" in text
    assert "[10:00:05] Sin cambios (online)." in text
    assert "CAMBIO DETECTADO: online -> offline" in text


def test_fixed_rate_schedule_does_not_drift(tmp_path):
    h = Harness(tmp_path, ["online"] * 6, duration_s=1.3)
    h.run()
    starts = [t - h.extractor.observed_at[0] for t in h.extractor.observed_at]
    assert starts == [0.0, 5.0, 10.0, 15.0, 20.0, 25.0]  # la duración de la lectura no se acumula


def test_slow_observation_skips_missed_ticks_instead_of_bursting(tmp_path):
    h = Harness(tmp_path, ["online"] * 3, duration_s=7.0)
    h.run()
    starts = [t - h.extractor.observed_at[0] for t in h.extractor.observed_at]
    assert starts == [0.0, 10.0, 20.0]


def test_backoff_after_consecutive_errors(tmp_path):
    script = [error()] * 6 + ["online"]
    h = Harness(tmp_path, script, duration_s=0.0, errors={"backoff_max_seconds": 30})
    h.run()
    starts = [t - h.extractor.observed_at[0] for t in h.extractor.observed_at]
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert gaps == [5.0, 10.0, 20.0, 30.0, 30.0, 30.0]
    assert h.types() == ["MONITOR_STARTED", "ERROR", "RECOVERED", "BASELINE", "MONITOR_STOPPED"]


def test_stops_after_max_consecutive_errors(tmp_path):
    h = Harness(tmp_path, [error()] * 50, max_cycles=50, errors={"max_consecutive_errors": 4})
    assert h.run() == EXIT_TOO_MANY_ERRORS
    assert h.extractor.calls == 4
    stopped = h.rows()[-1]
    assert stopped["tipo_evento"] == "MONITOR_STOPPED"
    assert "4 errores de lectura consecutivos" in stopped["detalle"]


# 16. Cierre ordenado con Ctrl+C ---------------------------------------------------------------

def test_ctrl_c_during_observation_finishes_it_and_closes_cleanly(tmp_path):
    holder = {}

    def press_ctrl_c(index):
        if index == 2:  # la señal llega mientras se lee la tercera observación
            holder["h"].monitor.request_stop("detenido por el usuario (Ctrl+C)")

    h = Harness(tmp_path, ["online", "online", "offline", "offline"], max_cycles=99, on_observe=press_ctrl_c)
    holder["h"] = h
    assert h.run() == EXIT_OK
    assert h.extractor.calls == 3  # no se empieza otra comprobación
    rows = h.rows()  # el CSV se puede leer completo
    assert all(len(r) == 24 and None not in r.values() for r in rows)
    assert rows[-1]["tipo_evento"] == "MONITOR_STOPPED"
    assert rows[-1]["detalle"] == "detenido por el usuario (Ctrl+C)"
    assert rows[-1]["estado_anterior"] == "offline"
    assert h.extractor.closed
    assert h.config.output.csv_path.read_bytes().endswith(b"\r\n")


def test_error_caused_by_shutdown_is_not_recorded(tmp_path):
    holder = {}

    def press_ctrl_c(index):
        if index == 1:
            holder["h"].monitor.request_stop("detenido por el usuario (Ctrl+C)")

    h = Harness(tmp_path, ["online", error(detail="Target page, context or browser has been closed")],
                max_cycles=99, on_observe=press_ctrl_c)
    holder["h"] = h
    h.run()
    assert "ERROR" not in h.types()


def test_keyboard_interrupt_still_writes_stop_marker(tmp_path):
    h = Harness(tmp_path, ["online", KeyboardInterrupt()], max_cycles=99)
    assert h.run() == 130
    assert h.rows()[-1]["detalle"] == "detención forzada (segundo Ctrl+C)"


# 10/11. Reinicio y recuperación -----------------------------------------------------------

def test_restart_resumes_without_duplicating_events(tmp_path):
    first = Harness(tmp_path, ["online", "online"], session="s1")
    first.run()
    first_rows = first.rows()

    second = Harness(tmp_path, ["online", "online", "offline"], session="s2",
                     wall_start=T0 + timedelta(hours=1))
    second.run()
    rows = second.rows()
    assert rows[: len(first_rows)] == first_rows  # el historial anterior sigue intacto
    new = [r["tipo_evento"] for r in rows[len(first_rows):]]
    assert new == ["MONITOR_STARTED", "TEXT_DISAPPEARED", "TEXT_APPEARED", "STATE_CHANGED", "MONITOR_STOPPED"]
    assert "estado restaurado" in rows[len(first_rows)]["detalle"]
    assert [r["tipo_evento"] for r in rows].count("BASELINE") == 1


def test_resume_disabled_sets_new_baseline(tmp_path):
    Harness(tmp_path, ["online"]).run()
    second = Harness(tmp_path, ["online"], session="s2", confirmation={"resume_state": False})
    second.run()
    assert second.types().count("BASELINE") == 2


# 9. Error de escritura del CSV durante la ejecución ---------------------------------------------

def test_csv_write_failure_is_retried_on_next_cycle(tmp_path, monkeypatch):
    real_fsync = os.fsync
    state = {"fail": False}

    def maybe_fail(fd):
        if state["fail"]:
            raise OSError(28, "No space left on device")
        return real_fsync(fd)

    def toggle(index):
        state["fail"] = index == 1  # falla solo al guardar el cambio de la segunda observación

    monkeypatch.setattr(os, "fsync", maybe_fail)
    h = Harness(tmp_path, ["online", "offline", "offline", "offline"], on_observe=toggle)
    h.run()
    assert "no se pudo escribir" in h.out.getvalue()
    assert h.types() == ["MONITOR_STARTED", "BASELINE", "TEXT_DISAPPEARED", "TEXT_APPEARED", "STATE_CHANGED",
                         "MONITOR_STOPPED"]


def test_detector_failure_is_an_error_not_a_change(tmp_path, monkeypatch):
    h = Harness(tmp_path, ["online", "online", "online"])
    calls = {"n": 0}
    original = h.monitor.detector.interpret

    def flaky(obs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("fallo simulado del detector")
        return original(obs)

    monkeypatch.setattr(h.monitor.detector, "interpret", flaky)
    h.run()
    assert h.types() == ["MONITOR_STARTED", "BASELINE", "ERROR", "RECOVERED", "MONITOR_STOPPED"]


def test_gap_in_wall_clock_is_reported(tmp_path):
    h = Harness(tmp_path, ["online"] * 3)
    normal_wait = h.monitor._wait

    def wait_with_sleep(seconds):
        if len(h.waits) == 1:
            # El Mac entra en reposo durante la espera: el reloj monotónico no avanza, la hora real sí.
            h.extractor.wall_start += timedelta(minutes=30)
        return normal_wait(seconds)

    h.monitor._wait = wait_with_sleep
    h.run()
    assert "No se observó la página durante 1800 s" in h.out.getvalue()
