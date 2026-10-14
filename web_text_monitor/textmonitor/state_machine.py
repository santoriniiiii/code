"""Máquina de estados: decide cuándo una diferencia es un cambio confirmado.

Reglas principales:

* Mantiene el último estado CONFIRMADO. Nada cambia hasta que un estado
  nuevo se observa `required_observations` veces seguidas.
* La primera vez (o tras perder la línea base) se registra BASELINE, nunca
  una transición que no se ha observado.
* UNKNOWN y ERROR no modifican el estado confirmado: un fallo de lectura
  nunca se interpreta como "el texto desapareció".
* Un episodio de lecturas fallidas se registra una sola vez (al empezar) y
  su fin se marca con RECOVERED, para no escribir una fila por intento.
* Mientras el estado no cambia no se genera ningún evento (NO_CHANGE).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Callable

from .models import (
    ConfirmedState,
    Event,
    EventType,
    Interpretation,
    ObservationKind,
    Outcome,
    Snapshot,
    StepResult,
)


@dataclass
class _Candidate:
    snapshot: Snapshot
    count: int
    first_seen_utc: datetime


@dataclass(frozen=True)
class TargetInfo:
    text: str
    mode: str


def _new_id() -> str:
    return str(uuid.uuid4())


class StateMachine:
    def __init__(
        self,
        targets: dict[str, TargetInfo],
        required_observations: int = 2,
        unknown_policy: str = "ignore",
        rebaseline_after_failures: int = 0,
        new_id: Callable[[], str] = _new_id,
    ):
        if required_observations < 1:
            raise ValueError("required_observations debe ser >= 1")
        self._targets = dict(targets)  # en orden de configuración
        self._required = required_observations
        self._unknown_policy = unknown_policy
        self._rebaseline_after = rebaseline_after_failures
        self._new_id = new_id

        self._confirmed: ConfirmedState | None = None
        self._candidate: _Candidate | None = None
        self._restored = False
        self._baseline_lost_detail = ""
        # Episodio de lecturas no válidas en curso
        self._failures = 0
        self._failures_by_kind: dict[ObservationKind, int] = {}
        self._failure_started: datetime | None = None

    # ------------------------------------------------------------------ estado
    @property
    def confirmed(self) -> ConfirmedState | None:
        return self._confirmed

    @property
    def consecutive_failures(self) -> int:
        return self._failures

    def restore(self, confirmed: ConfirmedState) -> None:
        """Usa como línea base el estado guardado por una ejecución anterior."""
        self._confirmed = confirmed
        self._candidate = None
        self._restored = True

    @property
    def all_target_texts(self) -> str:
        return " | ".join(info.text for info in self._targets.values())

    # ------------------------------------------------------------------ pasos
    def process(self, interp: Interpretation) -> StepResult:
        if interp.kind is ObservationKind.VALID:
            assert interp.snapshot is not None
            return self._process_valid(interp, interp.snapshot)
        return self._process_invalid(interp)

    def _process_invalid(self, interp: Interpretation) -> StepResult:
        obs = interp.observation
        events: list[Event] = []
        if self._failures == 0:
            self._failure_started = obs.started_utc
            event_type = EventType.ERROR if interp.kind is ObservationKind.ERROR else EventType.UNKNOWN
            previous = self._confirmed.snapshot.state if self._confirmed else ""
            events.append(
                Event(
                    event_id=self._new_id(),
                    event_type=event_type,
                    timestamp_utc=obs.started_utc,
                    searched_text=self.all_target_texts,
                    previous_state=previous,
                    duration_ms=obs.duration_ms,
                    method=obs.method,
                    excerpt=interp.excerpt,
                    detail=f"{interp.reason} (el estado anterior se conserva; no se registrará otra fila "
                    "hasta que la lectura se recupere)",
                )
            )
        self._failures += 1
        self._failures_by_kind[interp.kind] = self._failures_by_kind.get(interp.kind, 0) + 1

        if self._unknown_policy == "reset":
            self._candidate = None

        baseline_dropped = False
        if (
            self._rebaseline_after
            and self._failures >= self._rebaseline_after
            and (self._confirmed is not None or self._candidate is not None)
        ):
            if self._confirmed is not None:
                self._baseline_lost_detail = (
                    f"línea base restablecida tras {self._failures} observaciones no válidas; el último estado "
                    f"confirmado era {self._confirmed.snapshot.state!r} (visto por última vez "
                    f"{self._confirmed.last_seen_utc.isoformat(timespec='seconds')})"
                )
                baseline_dropped = True
            self._confirmed = None
            self._candidate = None
            self._restored = False

        outcome = Outcome.ERROR if interp.kind is ObservationKind.ERROR else Outcome.UNKNOWN
        return StepResult(
            outcome=outcome,
            interpretation=interp,
            confirmed=self._confirmed,
            events=events,
            candidate=self._candidate.snapshot if self._candidate else None,
            candidate_count=self._candidate.count if self._candidate else 0,
            required=self._required,
            baseline_dropped=baseline_dropped,
        )

    def _process_valid(self, interp: Interpretation, snap: Snapshot) -> StepResult:
        obs = interp.observation
        now = obs.started_utc
        events: list[Event] = []

        recovered_after = self._failures
        if self._failures:
            started = self._failure_started or now
            seconds = (now - started).total_seconds()
            breakdown = ", ".join(f"{k.value}: {v}" for k, v in self._failures_by_kind.items())
            events.append(
                Event(
                    event_id=self._new_id(),
                    event_type=EventType.RECOVERED,
                    timestamp_utc=now,
                    searched_text=self.all_target_texts,
                    new_state=snap.state,
                    duration_ms=obs.duration_ms,
                    method=obs.method,
                    first_seen_new_utc=now,
                    excerpt=snap.excerpt,
                    detail=f"lectura restablecida tras {self._failures} observaciones no válidas ({breakdown}) "
                    f"durante {seconds:.0f} s",
                )
            )
            self._failures = 0
            self._failures_by_kind = {}
            self._failure_started = None

        if self._confirmed is None:
            candidate = self._advance_candidate(snap, now)
            if candidate.count < self._required:
                return self._result(Outcome.BASELINE_PENDING, interp, events, recovered_after)
            self._confirmed = ConfirmedState(snapshot=snap, since_utc=candidate.first_seen_utc, last_seen_utc=now)
            self._candidate = None
            detail = self._baseline_lost_detail or "línea base inicial: no se registra ninguna transición anterior"
            self._baseline_lost_detail = ""
            events.append(
                Event(
                    event_id=self._new_id(),
                    event_type=EventType.BASELINE,
                    timestamp_utc=now,
                    searched_text=self._texts_for(snap.present) or self.all_target_texts,
                    new_text=snap.matches_text(),
                    new_state=snap.state,
                    confirmations=candidate.count,
                    duration_ms=obs.duration_ms,
                    method=obs.method,
                    first_seen_new_utc=candidate.first_seen_utc,
                    excerpt=snap.excerpt,
                    detail=detail,
                )
            )
            return self._result(Outcome.BASELINE, interp, events, recovered_after, confirmations=candidate.count)

        if snap.key == self._confirmed.snapshot.key:
            # Mismo estado: se actualiza la última vez visto y se descarta cualquier candidato.
            self._confirmed = replace(self._confirmed, snapshot=snap, last_seen_utc=now)
            self._candidate = None
            self._restored = False
            return self._result(Outcome.NO_CHANGE, interp, events, recovered_after)

        candidate = self._advance_candidate(snap, now)
        if candidate.count < self._required:
            return self._result(Outcome.CHANGE_PENDING, interp, events, recovered_after)

        events.extend(self._transition_events(self._confirmed, candidate, interp))
        self._confirmed = ConfirmedState(snapshot=snap, since_utc=candidate.first_seen_utc, last_seen_utc=now)
        self._candidate = None
        self._restored = False
        return self._result(Outcome.CHANGED, interp, events, recovered_after, confirmations=candidate.count)

    # --------------------------------------------------------------- ayudantes
    def _advance_candidate(self, snap: Snapshot, now: datetime) -> _Candidate:
        if self._candidate is not None and self._candidate.snapshot.key == snap.key:
            self._candidate.count += 1
            self._candidate.snapshot = snap
        else:
            self._candidate = _Candidate(snapshot=snap, count=1, first_seen_utc=now)
        return self._candidate

    def _texts_for(self, ids) -> str:
        return " | ".join(info.text for tid, info in self._targets.items() if tid in ids)

    def _transition_events(self, old: ConfirmedState, candidate: _Candidate, interp: Interpretation) -> list[Event]:
        obs = interp.observation
        new = candidate.snapshot
        transition_id = self._new_id()
        detail = (
            f"el cambio ocurrió entre {old.last_seen_utc.isoformat(timespec='seconds')} y "
            f"{candidate.first_seen_utc.isoformat(timespec='seconds')} (UTC)"
        )
        if self._restored:
            detail += "; el estado anterior procede de una ejecución previa del monitor"
        common = dict(
            timestamp_utc=obs.started_utc,
            previous_state=old.snapshot.state,
            new_state=new.state,
            confirmations=candidate.count,
            duration_ms=obs.duration_ms,
            last_seen_previous_utc=old.last_seen_utc,
            first_seen_new_utc=candidate.first_seen_utc,
            excerpt=new.excerpt,
            detail=detail,
            transition_id=transition_id,
        )
        events: list[Event] = []
        for tid, info in self._targets.items():
            if tid in old.snapshot.present and tid not in new.present:
                events.append(Event(
                    event_id=self._new_id(), event_type=EventType.TEXT_DISAPPEARED,
                    searched_text=info.text, previous_text=old.snapshot.match_for(tid),
                    method=f"{obs.method}; coincidencia {info.mode}", **common,
                ))
        for tid, info in self._targets.items():
            if tid in new.present and tid not in old.snapshot.present:
                events.append(Event(
                    event_id=self._new_id(), event_type=EventType.TEXT_APPEARED,
                    searched_text=info.text, new_text=new.match_for(tid),
                    method=f"{obs.method}; coincidencia {info.mode}", **common,
                ))
        if old.snapshot.state != new.state:
            events.append(Event(
                event_id=self._new_id(), event_type=EventType.STATE_CHANGED,
                searched_text=self._texts_for(old.snapshot.present | new.present),
                previous_text=old.snapshot.matches_text(), new_text=new.matches_text(),
                method=obs.method, **common,
            ))
        return events

    def _result(self, outcome: Outcome, interp: Interpretation, events: list[Event], recovered_after: int,
                confirmations: int = 0) -> StepResult:
        return StepResult(
            outcome=outcome,
            interpretation=interp,
            confirmed=self._confirmed,
            events=events,
            candidate=self._candidate.snapshot if self._candidate else None,
            candidate_count=self._candidate.count if self._candidate else confirmations,
            required=self._required,
            recovered_after=recovered_after,
        )
