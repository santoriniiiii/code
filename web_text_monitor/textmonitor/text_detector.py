"""Interpretación de lo leído: ¿qué textos están presentes y qué estado representan?

Este módulo no accede a la red ni guarda nada: recibe una RawObservation y
devuelve una Interpretation. Así se puede probar con datos simulados.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import AppConfig, TargetConfig, normalize_for_comparison
from .models import Interpretation, ObservationKind, RawObservation, ReadStatus, Snapshot


@dataclass(frozen=True)
class CompiledTarget:
    config: TargetConfig
    pattern: re.Pattern[str]

    @property
    def id(self) -> str:
        return self.config.id

    def search(self, text: str) -> str | None:
        """Devuelve el fragmento encontrado (tal como aparece) o None."""
        if self.config.mode == "exact":
            match = self.pattern.fullmatch(text)
        else:
            match = self.pattern.search(text)
        if match is None:
            return None
        return match.group(0) or self.config.text


def compile_target(target: TargetConfig, whitespace: str) -> CompiledTarget:
    flags = 0 if target.case_sensitive else re.IGNORECASE
    if target.mode == "regex":
        pattern = target.text
    else:
        needle = re.escape(normalize_for_comparison(target.text, whitespace))
        if target.mode == "word":
            pattern = rf"(?<!\w){needle}(?!\w)"
        else:  # contains / exact
            pattern = needle
    return CompiledTarget(config=target, pattern=re.compile(pattern, flags))


def truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1] + "…"


class TextDetector:
    def __init__(self, config: AppConfig):
        self._extraction = config.extraction
        self._matching = config.matching
        self._targets = [compile_target(t, config.matching.whitespace) for t in config.targets]

    @property
    def targets(self) -> list[CompiledTarget]:
        return list(self._targets)

    def normalize(self, text: str) -> str:
        return normalize_for_comparison(text, self._matching.whitespace)

    def interpret(self, obs: RawObservation) -> Interpretation:
        if obs.status is ReadStatus.ERROR:
            return Interpretation(ObservationKind.ERROR, obs, reason=obs.detail or "error de lectura")

        if obs.status is ReadStatus.ELEMENT_NOT_FOUND:
            if self._extraction.element_missing == "unknown":
                return Interpretation(
                    ObservationKind.UNKNOWN, obs, reason=f"elemento no encontrado: {obs.detail}".rstrip(": ")
                )
            texts: tuple[str, ...] = ()  # element_missing = "absent": el elemento ausente equivale a texto ausente
        else:
            texts = obs.texts
            if self._extraction.match_policy == "single" and len(texts) > 1:
                return Interpretation(
                    ObservationKind.UNKNOWN,
                    obs,
                    reason=f"el selector coincide con {len(texts)} elementos y match_policy = \"single\" exige uno",
                )
            if self._extraction.match_policy == "first":
                texts = texts[:1]

        normalized = [self.normalize(t) for t in texts]
        excerpt = truncate(
            " | ".join(" ".join(t.split()) for t in normalized if t.strip()), self._matching.excerpt_max_chars
        )

        matches: list[tuple[str, str]] = []
        for target in self._targets:
            for text in normalized:
                fragment = target.search(text)
                if fragment is not None:
                    matches.append((target.id, fragment))
                    break
        present = frozenset(tid for tid, _ in matches)

        states: list[str] = []
        for target in self._targets:
            if target.id in present and target.config.state not in states:
                states.append(target.config.state)

        if not states:
            if self._matching.no_match == "unknown":
                return Interpretation(
                    ObservationKind.UNKNOWN, obs, reason="ninguno de los textos configurados está presente",
                    excerpt=excerpt,
                )
            state = self._matching.no_match_state
        elif len(states) == 1:
            state = states[0]
        elif self._matching.multiple_states == "priority":
            state = states[0]
        elif self._matching.multiple_states == "conflict":
            return Interpretation(
                ObservationKind.UNKNOWN, obs,
                reason=f"varios estados a la vez ({', '.join(states)}) y multiple_states = \"conflict\"",
                excerpt=excerpt,
            )
        else:  # combined
            state = "+".join(states)

        snapshot = Snapshot(state=state, present=present, matches=tuple(matches), excerpt=excerpt)
        return Interpretation(ObservationKind.VALID, obs, snapshot=snapshot, excerpt=excerpt)
