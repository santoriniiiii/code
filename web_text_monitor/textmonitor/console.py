"""Mensajes de la terminal (separados de la lógica para poder probarla)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from typing import TextIO
from zoneinfo import ZoneInfo

from . import APP_NAME, __version__
from .config import AppConfig
from .models import EventType, ObservationKind, Outcome, StepResult


class Console:
    def __init__(self, tz: ZoneInfo, verbosity: str = "normal", stream: TextIO | None = None):
        self.tz = tz
        self.verbosity = verbosity
        self.stream = stream or sys.stdout

    def _now(self) -> str:
        return datetime.now(timezone.utc).astimezone(self.tz).strftime("%H:%M:%S")

    def say(self, message: str, at: datetime | None = None) -> None:
        stamp = at.astimezone(self.tz).strftime("%H:%M:%S") if at else self._now()
        print(f"[{stamp}] {message}", file=self.stream, flush=True)

    def plain(self, message: str = "") -> None:
        print(message, file=self.stream, flush=True)

    def banner(self, config: AppConfig, status: str) -> None:
        ex = config.extraction
        out = config.output
        self.plain("=" * 70)
        self.plain(f"{APP_NAME} v{__version__}")
        self.plain("=" * 70)
        self.plain(f"Página:            {config.page.label}")
        self.plain(f"URL:               {config.page.url}")
        frames = " -> ".join(ex.frame_selectors)
        self.plain(f"Elemento:          {ex.selector}" + (f"  (dentro de iframe: {frames})" if frames else ""))
        self.plain(f"Método:            {'navegador (Playwright)' if ex.method == 'browser' else 'HTTP (requests + BeautifulSoup)'}"
                   f"{'' if ex.method == 'http' else ', recarga en cada comprobación' if ex.reload_each_check else ', sin recargar'}")
        self.plain("Textos configurados:")
        for t in config.targets:
            case = "distingue mayúsculas" if t.case_sensitive else "no distingue mayúsculas"
            self.plain(f"  - {t.id}: {t.text!r} -> estado {t.state!r} (modo {t.mode}, {case})")
        self.plain(f"Sin coincidencias: {'estado ' + repr(config.matching.no_match_state) if config.matching.no_match == 'state' else 'UNKNOWN'}"
                   f" | varios estados a la vez: {config.matching.multiple_states}")
        self.plain(f"Intervalo:         {config.schedule.interval_s:g} s"
                   f" | confirmación: {config.confirmation.required_observations} observación(es) seguidas")
        self.plain(f"Historial (CSV):   {out.csv_path}")
        self.plain(f"Log técnico:       {out.log_path}")
        self.plain(f"Zona horaria:      {out.timezone}")
        self.plain(f"Estado:            {status}")
        for warning in config.warnings:
            self.plain(f"AVISO: {warning}")
        self.plain("-" * 70)

    def step(self, result: StepResult) -> None:
        interp = result.interpretation
        obs = interp.observation
        at = obs.started_utc
        v = self.verbosity

        if result.recovered_after:
            self.say(f"Lectura restablecida tras {result.recovered_after} observación(es) no válidas.", at)

        outcome = result.outcome
        if outcome is Outcome.BASELINE:
            snap = result.confirmed.snapshot
            found = snap.matches_text() or "ninguno de los textos configurados"
            self.say(f"Línea base establecida: {snap.state} (texto detectado: {found})", at)
        elif outcome is Outcome.BASELINE_PENDING:
            if v != "quiet":
                self.say(f"Estableciendo línea base: {result.candidate.state} "
                         f"({result.candidate_count}/{result.required})", at)
        elif outcome is Outcome.NO_CHANGE:
            if v != "quiet":
                self.say(f"Sin cambios ({result.confirmed.snapshot.state}).", at)
        elif outcome is Outcome.CHANGE_PENDING:
            if v != "quiet":
                self.say(f"Posible cambio: {result.confirmed.snapshot.state} -> {result.candidate.state} "
                         f"({result.candidate_count}/{result.required}), pendiente de confirmación.", at)
        elif outcome is Outcome.CHANGED:
            for event in result.events:
                if event.event_type is EventType.STATE_CHANGED:
                    self.say(f"CAMBIO DETECTADO: {event.previous_state} -> {event.new_state}", at)
            for event in result.events:
                if event.event_type is EventType.TEXT_APPEARED:
                    self.say(f"  Texto detectado: {event.new_text}", at)
                elif event.event_type is EventType.TEXT_DISAPPEARED:
                    self.say(f"  Texto desaparecido: {event.previous_text}", at)
        elif outcome in (Outcome.UNKNOWN, Outcome.ERROR):
            first = any(e.event_type in (EventType.UNKNOWN, EventType.ERROR) for e in result.events)
            if first or v != "quiet":
                kind = "No se pudo leer" if interp.kind is ObservationKind.ERROR else "No se pudo determinar el estado"
                keep = "el estado anterior se conserva" if result.confirmed else "aún no hay línea base"
                self.say(f"{kind} ({interp.reason}); {keep}.", at)
            if result.baseline_dropped:
                self.say("Demasiadas observaciones no válidas: se establecerá una nueva línea base.", at)

        if v == "verbose":
            self.plain(f"           duración {obs.duration_ms:.0f} ms | elementos {len(obs.texts)} | "
                       f"texto: {interp.excerpt!r}")
