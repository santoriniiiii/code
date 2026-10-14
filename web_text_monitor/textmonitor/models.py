"""Tipos de datos compartidos entre los módulos.

El flujo es:  extractor -> RawObservation -> detector -> Interpretation
              -> máquina de estados -> StepResult (con Event) -> CSV.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime


class ReadStatus(enum.Enum):
    """Resultado técnico de una lectura, antes de interpretar el texto."""

    OK = "OK"  # se encontró el elemento y se leyó su texto
    ELEMENT_NOT_FOUND = "ELEMENT_NOT_FOUND"  # la página respondió, pero el selector no coincidió
    ERROR = "ERROR"  # fallo técnico: red, HTTP >= 400, tiempo agotado, navegador caído...


@dataclass(frozen=True)
class RawObservation:
    """Lo que devuelve un extractor (navegador o HTTP) en cada comprobación."""

    status: ReadStatus
    started_utc: datetime
    duration_ms: float
    method: str
    texts: tuple[str, ...] = ()  # un texto por elemento que coincide con el selector
    detail: str = ""  # mensaje de error o explicación
    http_status: int | None = None
    final_url: str = ""


class ObservationKind(enum.Enum):
    VALID = "VALID"  # se pudo determinar el estado
    UNKNOWN = "UNKNOWN"  # la lectura funcionó, pero no permite determinar el estado
    ERROR = "ERROR"  # fallo técnico; no se sabe nada del texto


@dataclass(frozen=True)
class Snapshot:
    """Estado interpretado a partir de una observación válida."""

    state: str
    present: frozenset[str]  # identificadores de los textos encontrados
    matches: tuple[tuple[str, str], ...] = ()  # (id, fragmento tal como apareció), en orden de configuración
    excerpt: str = ""

    @property
    def key(self) -> tuple[str, frozenset[str]]:
        """Lo que se compara para decidir si hubo un cambio."""
        return (self.state, self.present)

    def match_for(self, target_id: str) -> str:
        for tid, fragment in self.matches:
            if tid == target_id:
                return fragment
        return ""

    def matches_text(self) -> str:
        return " | ".join(fragment for _, fragment in self.matches)


@dataclass(frozen=True)
class Interpretation:
    kind: ObservationKind
    observation: RawObservation
    snapshot: Snapshot | None = None
    reason: str = ""
    excerpt: str = ""


@dataclass(frozen=True)
class ConfirmedState:
    """Último estado confirmado por la máquina de estados."""

    snapshot: Snapshot
    since_utc: datetime  # primera observación del estado
    last_seen_utc: datetime  # última observación válida que lo mostró


class EventType(str, enum.Enum):
    # Eventos pedidos en la especificación
    TEXT_APPEARED = "TEXT_APPEARED"
    TEXT_DISAPPEARED = "TEXT_DISAPPEARED"
    STATE_CHANGED = "STATE_CHANGED"
    NO_CHANGE = "NO_CHANGE"  # nunca se guarda en el CSV
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"
    # Marcadores de cobertura: indican desde cuándo y hasta cuándo se observó
    BASELINE = "BASELINE"
    RECOVERED = "RECOVERED"
    MONITOR_STARTED = "MONITOR_STARTED"
    MONITOR_STOPPED = "MONITOR_STOPPED"


PERSISTABLE_EVENT_TYPES: frozenset[EventType] = frozenset(EventType) - {EventType.NO_CHANGE}


@dataclass(frozen=True)
class Event:
    """Una fila del historial CSV (sin los campos fijos de la sesión)."""

    event_id: str
    event_type: EventType
    timestamp_utc: datetime
    searched_text: str = ""
    previous_text: str = ""
    new_text: str = ""
    previous_state: str = ""
    new_state: str = ""
    confirmations: int | None = None
    duration_ms: float | None = None
    method: str = ""
    last_seen_previous_utc: datetime | None = None
    first_seen_new_utc: datetime | None = None
    excerpt: str = ""
    detail: str = ""
    transition_id: str = ""


class Outcome(enum.Enum):
    """Qué ocurrió en un paso de la máquina de estados (para la terminal)."""

    BASELINE_PENDING = "BASELINE_PENDING"
    BASELINE = "BASELINE"
    NO_CHANGE = "NO_CHANGE"
    CHANGE_PENDING = "CHANGE_PENDING"
    CHANGED = "CHANGED"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"


@dataclass
class StepResult:
    outcome: Outcome
    interpretation: Interpretation
    confirmed: ConfirmedState | None
    events: list[Event] = field(default_factory=list)
    candidate: Snapshot | None = None
    candidate_count: int = 0
    required: int = 1
    recovered_after: int = 0  # observaciones no válidas antes de esta (0 si no hubo)
    baseline_dropped: bool = False
