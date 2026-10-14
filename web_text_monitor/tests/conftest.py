"""Utilidades comunes de las pruebas: configuración, observaciones simuladas y reloj falso."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import pytest

from textmonitor.config import AppConfig, parse_config
from textmonitor.models import Interpretation, RawObservation, ReadStatus
from textmonitor.state_machine import StateMachine, TargetInfo
from textmonitor.text_detector import TextDetector

T0 = datetime(2026, 10, 14, 15, 0, 0, tzinfo=timezone.utc)  # 10:00:00 en Lima

BASE_CONFIG: dict[str, Any] = {
    "page": {"url": "https://ejemplo.test/estado", "label": "Prueba"},
    "extraction": {"method": "browser", "selector": "#estado"},
    "matching": {"multiple_states": "conflict"},
    "targets": [
        {"id": "online", "text": "online", "mode": "word"},
        {"id": "offline", "text": "offline", "mode": "word"},
    ],
    "confirmation": {"required_observations": 1},
    "schedule": {"interval_seconds": 5},
    "output": {
        "csv_path": "data/events.csv",
        "state_path": "data/state.json",
        "log_path": "logs/app.log",
        "timezone": "America/Lima",
    },
}


def deep_merge(base: dict, override: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def make_config(tmp_path: Path | None = None, **sections: Any) -> AppConfig:
    raw = deep_merge(BASE_CONFIG, sections)
    return parse_config(raw, base_dir=tmp_path or Path("/tmp/no-usar"))


def obs(*texts: str, t: float = 0.0, status: ReadStatus = ReadStatus.OK, detail: str = "",
        duration_ms: float = 120.0) -> RawObservation:
    """Observación simulada `t` segundos después de T0."""
    return RawObservation(status=status, started_utc=T0 + timedelta(seconds=t), duration_ms=duration_ms,
                          method="simulado", texts=texts, detail=detail)


def error(t: float = 0.0, detail: str = "net::ERR_CONNECTION_REFUSED") -> RawObservation:
    return obs(t=t, status=ReadStatus.ERROR, detail=detail)


def missing(t: float = 0.0) -> RawObservation:
    return obs(t=t, status=ReadStatus.ELEMENT_NOT_FOUND, detail="'#estado' no apareció")


def build_machine(config: AppConfig, ids: Callable[[], str] | None = None) -> StateMachine:
    kwargs = {}
    if ids is not None:
        kwargs["new_id"] = ids
    return StateMachine(
        {t.id: TargetInfo(text=t.text, mode=t.mode) for t in config.targets},
        required_observations=config.confirmation.required_observations,
        unknown_policy=config.confirmation.unknown_policy,
        rebaseline_after_failures=config.confirmation.rebaseline_after_failures,
        **kwargs,
    )


class Pipeline:
    """Detector + máquina de estados alimentados con observaciones simuladas."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.detector = TextDetector(config)
        self.machine = build_machine(config)
        self.results = []

    def feed(self, observation: RawObservation):
        interp: Interpretation = self.detector.interpret(observation)
        result = self.machine.process(interp)
        self.results.append(result)
        return result

    def feed_texts(self, *items: str | RawObservation, start: float = 0.0, step: float = 5.0):
        """Cada elemento es un texto (observación OK) o una RawObservation ya construida."""
        out = []
        for i, item in enumerate(items):
            if isinstance(item, RawObservation):
                out.append(self.feed(item))
            else:
                out.append(self.feed(obs(item, t=start + i * step)))
        return out

    @property
    def events(self):
        return [e for r in self.results for e in r.events]

    def types(self) -> list[str]:
        return [e.event_type.value for e in self.events]


@pytest.fixture
def pipeline_factory():
    def factory(**sections: Any) -> Pipeline:
        return Pipeline(make_config(**sections))

    return factory


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class ScriptedExtractor:
    """Extractor simulado: devuelve observaciones de un guion y mide el reloj falso."""

    method = "simulado"

    def __init__(self, script: list[Any], clock: FakeClock, wall_start: datetime = T0,
                 duration_s: float = 0.2, on_observe: Callable[[int], None] | None = None):
        self.script = list(script)
        self.clock = clock
        self.wall_start = wall_start
        self.base_mono = clock.now
        self.duration_s = duration_s
        self.on_observe = on_observe
        self.calls = 0
        self.observed_at: list[float] = []
        self.started = False
        self.closed = False

    def wall_now(self) -> datetime:
        return self.wall_start + timedelta(seconds=self.clock.now - self.base_mono)

    def start(self) -> None:
        self.started = True

    def observe(self) -> RawObservation:
        index = self.calls
        self.calls += 1
        self.observed_at.append(self.clock.now)
        started = self.wall_now()
        item = self.script[min(index, len(self.script) - 1)]
        self.clock.advance(self.duration_s)
        if self.on_observe:
            self.on_observe(index)
        if isinstance(item, RawObservation):
            return RawObservation(status=item.status, started_utc=started, duration_ms=self.duration_s * 1000,
                                  method=self.method, texts=item.texts, detail=item.detail)
        if isinstance(item, BaseException):
            raise item
        return RawObservation(status=ReadStatus.OK, started_utc=started, duration_ms=self.duration_s * 1000,
                              method=self.method, texts=(item,))

    def close(self) -> None:
        self.closed = True
