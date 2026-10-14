"""Guarda el último estado confirmado para poder detener y reanudar el monitor.

El archivo es un JSON pequeño que se escribe de forma atómica (archivo
temporal + os.replace), de modo que un cierre brusco no lo deja a medias.
Incluye la huella de la configuración: si se cambia la URL, el selector o los
textos, el estado guardado no se reutiliza.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from .models import ConfirmedState, Snapshot

log = logging.getLogger(__name__)

FORMAT_VERSION = 1


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds")


class StateStore:
    def __init__(self, path: Path, fingerprint: str):
        self.path = path
        self.fingerprint = fingerprint

    def load(self) -> tuple[ConfirmedState | None, str]:
        """Devuelve (estado, explicación). Nunca lanza excepciones por el contenido del archivo."""
        if not self.path.exists():
            return None, "no hay estado guardado de una ejecución anterior"
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if data.get("version") != FORMAT_VERSION:
                return None, f"el archivo de estado tiene otra versión de formato ({data.get('version')!r}); se ignora"
            if data.get("config_fingerprint") != self.fingerprint:
                return None, ("la configuración de lo que se observa cambió desde la última ejecución; "
                              "se establecerá una nueva línea base")
            confirmed = data.get("confirmed")
            if confirmed is None:
                return None, "la ejecución anterior terminó sin un estado confirmado"
            snapshot = Snapshot(
                state=confirmed["state"],
                present=frozenset(confirmed["present"]),
                matches=tuple((m[0], m[1]) for m in confirmed["matches"]),
                excerpt=confirmed.get("excerpt", ""),
            )
            state = ConfirmedState(
                snapshot=snapshot,
                since_utc=datetime.fromisoformat(confirmed["since_utc"]),
                last_seen_utc=datetime.fromisoformat(confirmed["last_seen_utc"]),
            )
            return state, (f"estado restaurado de la ejecución anterior: {snapshot.state!r} "
                           f"(última observación {_iso(state.last_seen_utc)})")
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            log.warning("No se pudo leer el archivo de estado %s: %s", self.path, exc)
            return None, f"el archivo de estado no se pudo leer ({exc}); se establecerá una nueva línea base"

    def save(self, confirmed: ConfirmedState | None) -> None:
        """Escribe el estado de forma atómica. Lanza OSError si no se puede."""
        payload = {
            "version": FORMAT_VERSION,
            "config_fingerprint": self.fingerprint,
            "saved_utc": _iso(datetime.now(timezone.utc)),
            "confirmed": None,
        }
        if confirmed is not None:
            snap = confirmed.snapshot
            payload["confirmed"] = {
                "state": snap.state,
                "present": sorted(snap.present),
                "matches": [list(m) for m in snap.matches],
                "excerpt": snap.excerpt,
                "since_utc": _iso(confirmed.since_utc),
                "last_seen_utc": _iso(confirmed.last_seen_utc),
            }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, self.path)
