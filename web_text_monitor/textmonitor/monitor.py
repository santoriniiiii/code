"""Bucle principal: observar -> interpretar -> comparar -> registrar -> esperar.

* El intervalo se gestiona con un reloj monotónico (time.monotonic), que no
  salta si cambia la hora del sistema. Las marcas de tiempo de los registros
  usan la hora real en UTC.
* Las comprobaciones siguen una rejilla fija (0, 5, 10, 15 s...): la duración
  de cada lectura no se acumula como retraso. Si una lectura tarda más que el
  intervalo, se omiten las comprobaciones perdidas en lugar de encadenarlas.
* Tras errores técnicos consecutivos la espera crece (5, 10, 20, 40, 60 s...)
  y, si se configura, el programa se detiene tras N errores seguidos.
* Ctrl+C solo activa una bandera: la lectura en curso termina, se registra
  MONITOR_STOPPED y se cierra el navegador sin dejar el CSV a medias.

El intervalo NO garantiza ver cambios que empiecen y terminen entre dos
observaciones: lo que dura menos que el intervalo puede pasar inadvertido.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

from . import APP_NAME, __version__
from .browser_manager import BrowserStartError
from .config import AppConfig
from .console import Console
from .event_logger import CsvEventLogger
from .models import (
    Event,
    EventType,
    Interpretation,
    ObservationKind,
    Outcome,
    RawObservation,
    ReadStatus,
    StepResult,
)
from .state_machine import StateMachine
from .state_store import StateStore
from .text_detector import TextDetector

log = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_STARTUP = 2
EXIT_TOO_MANY_ERRORS = 3
EXIT_FORCED = 130

STATE_SAVE_EVERY_S = 30.0


class Extractor(Protocol):
    method: str

    def start(self) -> None: ...

    def observe(self) -> RawObservation: ...

    def close(self) -> None: ...


class Monitor:
    def __init__(
        self,
        config: AppConfig,
        extractor: Extractor,
        detector: TextDetector,
        machine: StateMachine,
        event_logger: CsvEventLogger,
        state_store: StateStore,
        console: Console,
        *,
        clock: Callable[[], float] = time.monotonic,
        now_utc: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        wait: Callable[[float], bool] | None = None,
    ):
        self.config = config
        self.extractor = extractor
        self.detector = detector
        self.machine = machine
        self.event_logger = event_logger
        self.state_store = state_store
        self.console = console
        self._clock = clock
        self._now_utc = now_utc
        self._stop = threading.Event()
        self._wait = wait or self._stop.wait
        self._stop_reason = ""
        self._last_state_save = float("-inf")
        self._expected_next_wall: datetime | None = None
        self.cycles = 0

    # ----------------------------------------------------------------- control
    def request_stop(self, reason: str) -> None:
        if not self._stop.is_set():
            self._stop_reason = reason
            self._stop.set()

    @property
    def stop_requested(self) -> bool:
        return self._stop.is_set()

    # ------------------------------------------------------------------- run
    def run(self) -> int:
        exit_code = EXIT_OK
        restored_msg = self._restore_state()
        self.console.say(restored_msg[:1].upper() + restored_msg[1:] + ".")
        self._record([self._session_event(
            EventType.MONITOR_STARTED,
            f"{APP_NAME} {__version__}; método: {self.extractor.method}; intervalo "
            f"{self.config.schedule.interval_s:g} s; confirmación "
            f"{self.config.confirmation.required_observations}; {restored_msg}",
        )])
        try:
            try:
                self.extractor.start()
            except BrowserStartError as exc:
                self.console.say(f"ERROR: {exc}")
                log.error("No se pudo iniciar el extractor: %s", exc)
                self._stop_reason = f"no se pudo iniciar el navegador: {exc}"
                return EXIT_STARTUP
            self.console.say("En ejecución. Pulsa Ctrl+C para detener.")
            exit_code = self._loop()
        except KeyboardInterrupt:
            self._stop_reason = "detención forzada (segundo Ctrl+C)"
            exit_code = EXIT_FORCED
        except Exception as exc:
            log.exception("Error inesperado en el bucle principal")
            self.console.say(f"ERROR inesperado: {type(exc).__name__}: {exc}. Detalles en {self.config.output.log_path}")
            self._stop_reason = f"error inesperado: {type(exc).__name__}: {exc}"
            exit_code = EXIT_UNEXPECTED
        finally:
            self._shutdown()
        return exit_code

    def _restore_state(self) -> str:
        if not self.config.confirmation.resume_state:
            return "resume_state = false: se establecerá una nueva línea base"
        confirmed, message = self.state_store.load()
        if confirmed is not None:
            self.machine.restore(confirmed)
        log.info(message)
        return message

    def _loop(self) -> int:
        interval = self.config.schedule.interval_s
        max_errors = self.config.schedule.max_consecutive_errors
        next_due = self._clock()
        consecutive_errors = 0

        while not self._stop.is_set():
            obs = self._observe()
            self.cycles += 1
            if self._stop.is_set() and obs.status is ReadStatus.ERROR:
                # Muy probablemente la causa es la propia detención: no se registra como error.
                log.info("Observación interrumpida por la detención; se descarta: %s", obs.detail)
                break
            self._warn_if_gap(obs)
            interp = self._interpret(obs)
            result = self.machine.process(interp)
            self._record(result.events)
            self._maybe_save_state(result)
            self.console.step(result)
            self._log_step(result)

            consecutive_errors = consecutive_errors + 1 if interp.kind is ObservationKind.ERROR else 0
            if max_errors and consecutive_errors >= max_errors:
                self._stop_reason = (f"detenido tras {consecutive_errors} errores de lectura consecutivos "
                                     f"(max_consecutive_errors = {max_errors})")
                self.console.say(f"Se alcanzó el máximo de errores consecutivos ({max_errors}); el monitor se detiene.")
                return EXIT_TOO_MANY_ERRORS

            now = self._clock()
            if consecutive_errors:
                exponent = min(consecutive_errors - 1, 20)
                delay = min(interval * 2 ** exponent, max(self.config.schedule.backoff_max_s, interval))
                next_due = now + delay
                if delay > interval and self.console.verbosity != "quiet":
                    self.console.say(f"Próximo intento en {delay:.0f} s.")
            else:
                next_due += interval
                if next_due <= now:
                    skipped = int((now - next_due) // interval) + 1
                    log.warning("La comprobación tardó más que el intervalo (%g s); se omiten %d comprobación(es)",
                                interval, skipped)
                    next_due += skipped * interval
            self._expected_next_wall = self._now_utc() + timedelta(seconds=next_due - now)
            self._wait(max(0.0, next_due - self._clock()))
        return EXIT_OK

    # ------------------------------------------------------------- ayudantes
    def _observe(self) -> RawObservation:
        try:
            return self.extractor.observe()
        except Exception as exc:  # los extractores no deberían lanzar; por si acaso
            log.exception("El extractor lanzó una excepción")
            return RawObservation(status=ReadStatus.ERROR, started_utc=self._now_utc(), duration_ms=0.0,
                                  method=getattr(self.extractor, "method", "?"),
                                  detail=f"fallo del extractor: {type(exc).__name__}: {exc}")

    def _interpret(self, obs: RawObservation) -> Interpretation:
        try:
            return self.detector.interpret(obs)
        except Exception as exc:
            log.exception("El detector falló")
            return Interpretation(ObservationKind.ERROR, obs, reason=f"fallo del detector: {type(exc).__name__}: {exc}")

    def _record(self, events: list[Event]) -> None:
        for event in events:
            log.info("Evento %s: %s -> %s %s", event.event_type.value, event.previous_state, event.new_state,
                     event.detail)
        if not events and not self.event_logger.pending_count:
            return
        if not self.event_logger.write(events):
            self.console.say(f"AVISO: no se pudo escribir en {self.event_logger.path}; "
                             f"{self.event_logger.pending_count} fila(s) pendientes, se reintentará. "
                             f"Detalles en {self.config.output.log_path}")

    def _maybe_save_state(self, result: StepResult) -> None:
        if not self.config.confirmation.resume_state:
            return
        now = self._clock()
        changed = bool(result.events) or result.outcome in (Outcome.BASELINE, Outcome.CHANGED) or result.baseline_dropped
        periodic = result.interpretation.kind is ObservationKind.VALID and now - self._last_state_save >= STATE_SAVE_EVERY_S
        if changed or periodic:
            self._save_state()

    def _save_state(self) -> None:
        try:
            self.state_store.save(self.machine.confirmed)
            self._last_state_save = self._clock()
        except OSError as exc:
            log.warning("No se pudo guardar el estado en %s: %s", self.state_store.path, exc)

    def _warn_if_gap(self, obs: RawObservation) -> None:
        if self._expected_next_wall is None:
            return
        late = (obs.started_utc - self._expected_next_wall).total_seconds()
        if late > max(3 * self.config.schedule.interval_s, 30):
            msg = (f"No se observó la página durante {late:.0f} s más de lo previsto "
                   "(¿el Mac estuvo en reposo o el programa bloqueado?). Los cambios de ese periodo no se vieron.")
            self.console.say(f"AVISO: {msg}", obs.started_utc)
            log.warning(msg)

    def _log_step(self, result: StepResult) -> None:
        interp = result.interpretation
        if interp.kind is ObservationKind.VALID:
            log.debug("%s: estado=%s duración=%.0f ms texto=%r", result.outcome.value, interp.snapshot.state,
                      interp.observation.duration_ms, interp.excerpt)
        else:
            log.warning("%s: %s (duración %.0f ms)", interp.kind.value, interp.reason, interp.observation.duration_ms)

    def _session_event(self, event_type: EventType, detail: str) -> Event:
        confirmed = self.machine.confirmed
        state = confirmed.snapshot.state if confirmed else ""
        return Event(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            timestamp_utc=self._now_utc(),
            searched_text=self.machine.all_target_texts,
            previous_state=state if event_type is EventType.MONITOR_STOPPED else "",
            new_state=state if event_type is EventType.MONITOR_STARTED else "",
            method=getattr(self.extractor, "method", ""),
            detail=detail,
        )

    def _shutdown(self) -> None:
        reason = self._stop_reason or "fin del programa"
        try:
            self.extractor.close()
        except Exception as exc:
            log.warning("Error al cerrar el extractor: %s", exc)
        if self.config.confirmation.resume_state:
            self._save_state()
        self._record([self._session_event(EventType.MONITOR_STOPPED, reason)])
        unsaved = self.event_logger.close()
        if unsaved:
            log.error("%d fila(s) NO se pudieron guardar en el CSV; se copian aquí en JSON:", len(unsaved))
            for row in unsaved:
                log.error("FILA NO GUARDADA %s", json.dumps(row, ensure_ascii=False))
            self.console.say(f"AVISO: {len(unsaved)} fila(s) no se pudieron guardar en el CSV; "
                             f"se copiaron en {self.config.output.log_path}")
        log.info("Monitor detenido: %s", reason)
        self.console.say(f"Monitor detenido ({reason}). Historial: {self.config.output.csv_path}")
