"""Historial persistente de eventos en CSV (compatible con Excel).

* UTF-8 con BOM: Excel reconoce así las tildes y la ñ.
* El archivo nunca se sobrescribe: solo se añaden filas. Si ya existe con
  otras columnas u otro separador, el monitor se niega a escribir en él.
* Cada lote de filas se escribe con una sola llamada, se fuerza a disco
  (fsync) y, si la escritura falla a medias, se recorta lo escrito.
* Si no se puede escribir (permisos, disco lleno, archivo bloqueado), las
  filas quedan en una cola en memoria y se reintentan en cada comprobación.
* Un archivo .lock impide que dos monitores escriban en el mismo CSV.
"""

from __future__ import annotations

import csv
import io
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from .models import Event, EventType

try:
    import fcntl
except ImportError:  # Windows: no hay bloqueo de archivos de este tipo
    fcntl = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

CSV_COLUMNS = [
    "id_evento",
    "fecha_hora_utc",
    "fecha_hora_local",
    "fecha_local",
    "hora_local",
    "zona_horaria",
    "tipo_evento",
    "pagina",
    "url",
    "selector",
    "texto_buscado",
    "texto_anterior",
    "texto_nuevo",
    "estado_anterior",
    "estado_nuevo",
    "observaciones_confirmacion",
    "duracion_observacion_ms",
    "metodo_deteccion",
    "ultima_obs_estado_anterior_utc",
    "primera_obs_estado_nuevo_utc",
    "extracto_texto",
    "detalle",
    "id_transicion",
    "id_sesion",
]

BOM = "﻿"
MAX_PENDING = 10_000
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


class EventLogError(Exception):
    """Problema que impide usar el archivo CSV (se informa al arrancar)."""


def excel_safe(value: str) -> str:
    """Evita que Excel interprete como fórmula un texto copiado de la página."""
    if value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def iso(dt: datetime | None, tz: ZoneInfo | None = None) -> str:
    if dt is None:
        return ""
    if tz is not None:
        dt = dt.astimezone(tz)
    return dt.isoformat(timespec="milliseconds")


class CsvEventLogger:
    def __init__(
        self,
        path: Path,
        *,
        timezone: str,
        page_label: str,
        url: str,
        selector: str,
        session_id: str,
        record_events: frozenset[EventType],
        delimiter: str = ",",
    ):
        self.path = path
        self.tz_name = timezone
        self.tz = ZoneInfo(timezone)
        self.page_label = page_label
        self.url = url
        self.selector = selector
        self.session_id = session_id
        self.record_events = record_events
        self.delimiter = delimiter
        self._pending: list[list[str]] = []
        self._lock_fh = None

    # --------------------------------------------------------------- apertura
    def open(self) -> None:
        """Prepara el archivo. Lanza EventLogError con un mensaje claro si no es posible."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise EventLogError(f"No se pudo crear la carpeta {self.path.parent}: {exc}") from exc
        self._acquire_lock()
        try:
            if not self.path.exists() or self.path.stat().st_size == 0:
                mode = "xb" if not self.path.exists() else "ab"
                with self.path.open(mode) as fh:
                    fh.write((BOM + self._format_rows([CSV_COLUMNS])).encode("utf-8"))
                    fh.flush()
                    os.fsync(fh.fileno())
                log.info("Creado el historial %s", self.path)
            else:
                self._check_existing_header()
                self._repair_last_line()
        except EventLogError:
            self.close()
            raise
        except OSError as exc:
            self.close()
            raise EventLogError(f"No se pudo preparar el historial {self.path}: {exc}") from exc

    def _acquire_lock(self) -> None:
        if fcntl is None:
            log.warning("Sin bloqueo de archivo en este sistema; no ejecutes dos monitores con el mismo CSV")
            return
        lock_path = self.path.with_name(self.path.name + ".lock")
        try:
            fh = lock_path.open("a")
        except OSError as exc:
            raise EventLogError(f"No se pudo crear {lock_path}: {exc}") from exc
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            raise EventLogError(
                f"Otro monitor ya está escribiendo en {self.path}. Detenlo o usa otro csv_path."
            ) from None
        self._lock_fh = fh

    def _check_existing_header(self) -> None:
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as fh:
                first_line = fh.readline()
        except UnicodeDecodeError:
            first_line = ""  # no es UTF-8 (p. ej. guardado desde Excel con otra codificación)
        header = next(csv.reader([first_line], delimiter=self.delimiter), [])
        if header != CSV_COLUMNS:
            raise EventLogError(
                f"El archivo {self.path} ya existe pero sus columnas o su separador no coinciden con los de este "
                f"programa (separador configurado: {self.delimiter!r}). Para no dañar el historial no se escribirá "
                "en él. Usa otro csv_path o restaura el archivo original (¿se guardó desde Excel?)."
            )

    def _repair_last_line(self) -> None:
        """Si un cierre brusco dejó la última línea sin terminar, la cierra."""
        with self.path.open("rb") as fh:
            fh.seek(-1, os.SEEK_END)
            last = fh.read(1)
        if last != b"\n":
            log.warning("La última línea de %s estaba incompleta; se añade un salto de línea", self.path)
            with self.path.open("ab") as fh:
                fh.write(b"\r\n")

    # -------------------------------------------------------------- escritura
    def _format_rows(self, rows: list[list[str]]) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=self.delimiter, lineterminator="\r\n")
        writer.writerows(rows)
        return buffer.getvalue()

    def to_row(self, event: Event) -> list[str]:
        local = event.timestamp_utc.astimezone(self.tz)
        values = [
            event.event_id,
            iso(event.timestamp_utc),
            iso(event.timestamp_utc, self.tz),
            local.strftime("%Y-%m-%d"),
            local.strftime("%H:%M:%S"),
            self.tz_name,
            event.event_type.value,
            self.page_label,
            self.url,
            self.selector,
            event.searched_text,
            event.previous_text,
            event.new_text,
            event.previous_state,
            event.new_state,
            "" if event.confirmations is None else str(event.confirmations),
            "" if event.duration_ms is None else str(round(event.duration_ms)),
            event.method,
            iso(event.last_seen_previous_utc),
            iso(event.first_seen_new_utc),
            event.excerpt,
            event.detail,
            event.transition_id,
            self.session_id,
        ]
        return [excel_safe(v) for v in values]

    def write(self, events: list[Event]) -> bool:
        """Añade los eventos al CSV. Devuelve False si quedaron filas pendientes."""
        rows = [self.to_row(e) for e in events if e.event_type in self.record_events]
        if rows:
            self._pending.extend(rows)
            if len(self._pending) > MAX_PENDING:
                dropped = len(self._pending) - MAX_PENDING
                log.error("Cola de eventos pendientes llena: se descartan %d eventos antiguos", dropped)
                del self._pending[:dropped]
        return self.flush_pending()

    def flush_pending(self) -> bool:
        if not self._pending:
            return True
        data = self._format_rows(self._pending).encode("utf-8")
        try:
            with self.path.open("ab") as fh:
                start = fh.seek(0, os.SEEK_END)
                try:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                except OSError:
                    try:
                        fh.truncate(start)  # no dejar una fila a medias
                    except OSError:
                        pass
                    raise
        except OSError as exc:
            log.error("No se pudo escribir en %s (%d eventos pendientes): %s", self.path, len(self._pending), exc)
            return False
        self._pending.clear()
        return True

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    def close(self) -> list[list[str]]:
        """Último intento de escritura. Devuelve las filas que no se pudieron guardar."""
        self.flush_pending()
        unsaved = list(self._pending)
        if self._lock_fh is not None:
            try:
                self._lock_fh.close()  # cerrar libera el bloqueo
            except OSError:
                pass
            self._lock_fh = None
        return unsaved
