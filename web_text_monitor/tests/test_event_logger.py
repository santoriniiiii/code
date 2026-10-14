"""Pruebas del historial CSV: creación, conservación, errores de escritura y zona horaria."""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest
from conftest import T0

from textmonitor.event_logger import BOM, CSV_COLUMNS, CsvEventLogger, EventLogError, excel_safe
from textmonitor.models import PERSISTABLE_EVENT_TYPES, Event, EventType


def make_logger(path: Path, tz: str = "America/Lima", delimiter: str = ",", record=PERSISTABLE_EVENT_TYPES,
                session: str = "sesion-1") -> CsvEventLogger:
    return CsvEventLogger(path, timezone=tz, page_label="Prueba", url="https://ejemplo.test", selector="#estado",
                          session_id=session, record_events=frozenset(record), delimiter=delimiter)


def event(event_type=EventType.STATE_CHANGED, when: datetime = T0, **kwargs) -> Event:
    defaults = dict(previous_state="online", new_state="offline", previous_text="online", new_text="offline",
                    searched_text="online | offline", confirmations=2, duration_ms=123.4, method="simulado")
    defaults.update(kwargs)
    return Event(event_id=f"id-{event_type.value}-{when.timestamp()}", event_type=event_type, timestamp_utc=when,
                 **defaults)


def read_rows(path: Path, delimiter: str = ",") -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh, delimiter=delimiter))


def test_creates_missing_folders_and_file_with_bom_and_header(tmp_path):
    path = tmp_path / "carpeta" / "nueva" / "events.csv"
    logger = make_logger(path)
    logger.open()
    logger.close()
    raw = path.read_bytes()
    assert raw.startswith(BOM.encode("utf-8"))  # Excel reconoce UTF-8
    assert raw.count(BOM.encode("utf-8")) == 1
    assert raw.decode("utf-8-sig").splitlines()[0] == ",".join(CSV_COLUMNS)


def test_rows_contain_required_fields_and_accents(tmp_path):
    path = tmp_path / "events.csv"
    logger = make_logger(path)
    logger.open()
    assert logger.write([event(new_text="Sin conexión", excerpt="Estado: sin conexión")])
    logger.close()
    row = read_rows(path)[0]
    assert row["tipo_evento"] == "STATE_CHANGED"
    assert row["fecha_hora_utc"] == "2026-10-14T15:00:00.000+00:00"
    assert row["fecha_hora_local"] == "2026-10-14T10:00:00.000-05:00"
    assert (row["fecha_local"], row["hora_local"]) == ("2026-10-14", "10:00:00")
    assert row["texto_nuevo"] == "Sin conexión"
    assert row["observaciones_confirmacion"] == "2"
    assert row["duracion_observacion_ms"] == "123"
    assert row["pagina"] == "Prueba" and row["url"] == "https://ejemplo.test"
    assert row["id_sesion"] == "sesion-1"


def test_restart_appends_and_keeps_history(tmp_path):
    path = tmp_path / "events.csv"
    first = make_logger(path, session="s1")
    first.open()
    first.write([event(EventType.BASELINE)])
    first.close()

    second = make_logger(path, session="s2")
    second.open()
    second.write([event(EventType.STATE_CHANGED)])
    second.close()

    rows = read_rows(path)
    assert [r["id_sesion"] for r in rows] == ["s1", "s2"]
    assert path.read_bytes().count(BOM.encode("utf-8")) == 1  # el BOM no se repite al añadir


def test_refuses_file_with_other_columns_and_leaves_it_untouched(tmp_path):
    path = tmp_path / "events.csv"
    path.write_text("fecha;evento\n2026-01-01;algo\n", encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(EventLogError, match="no coinciden"):
        make_logger(path).open()
    assert path.read_bytes() == before


def test_refuses_file_saved_with_another_encoding(tmp_path):
    path = tmp_path / "events.csv"
    path.write_bytes("id_evento;descripción\n".encode("cp1252"))
    with pytest.raises(EventLogError, match="no coinciden"):
        make_logger(path).open()


def test_refuses_changing_delimiter_of_existing_file(tmp_path):
    path = tmp_path / "events.csv"
    logger = make_logger(path, delimiter=",")
    logger.open()
    logger.close()
    with pytest.raises(EventLogError):
        make_logger(path, delimiter=";").open()


def test_semicolon_delimiter(tmp_path):
    path = tmp_path / "events.csv"
    logger = make_logger(path, delimiter=";")
    logger.open()
    logger.write([event()])
    logger.close()
    assert read_rows(path, delimiter=";")[0]["estado_nuevo"] == "offline"


def test_parent_path_is_a_file_gives_clear_error(tmp_path):
    blocker = tmp_path / "no_es_carpeta"
    blocker.write_text("x")
    with pytest.raises(EventLogError, match="No se pudo crear la carpeta"):
        make_logger(blocker / "events.csv").open()


def test_second_monitor_on_same_csv_is_rejected(tmp_path):
    path = tmp_path / "events.csv"
    first = make_logger(path)
    first.open()
    try:
        with pytest.raises(EventLogError, match="Otro monitor"):
            make_logger(path).open()
    finally:
        first.close()
    second = make_logger(path)  # tras cerrar el primero, se puede volver a abrir
    second.open()
    second.close()


# 9. Error de escritura del CSV -------------------------------------------------------------

def test_write_error_keeps_rows_pending_and_retries(tmp_path, monkeypatch):
    path = tmp_path / "events.csv"
    logger = make_logger(path)
    logger.open()
    logger.write([event(EventType.BASELINE)])
    size_before = path.stat().st_size

    real_fsync = os.fsync

    def failing_fsync(fd):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "fsync", failing_fsync)
    assert logger.write([event(EventType.STATE_CHANGED)]) is False
    assert logger.pending_count == 1
    assert path.stat().st_size == size_before  # lo escrito a medias se recorta

    monkeypatch.setattr(os, "fsync", real_fsync)
    assert logger.flush_pending() is True
    assert logger.pending_count == 0
    logger.close()
    assert [r["tipo_evento"] for r in read_rows(path)] == ["BASELINE", "STATE_CHANGED"]


def test_unsaved_rows_are_returned_on_close(tmp_path, monkeypatch):
    path = tmp_path / "events.csv"
    logger = make_logger(path)
    logger.open()
    original_open = Path.open

    def broken_open(self, mode="r", *args, **kwargs):
        if self == path and "a" in mode:
            raise PermissionError(13, "Permission denied")
        return original_open(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", broken_open)
    assert logger.write([event()]) is False
    unsaved = logger.close()
    assert len(unsaved) == 1 and unsaved[0][6] == "STATE_CHANGED"


def test_incomplete_last_line_is_repaired(tmp_path):
    path = tmp_path / "events.csv"
    logger = make_logger(path)
    logger.open()
    logger.write([event(EventType.BASELINE)])
    logger.close()
    with path.open("ab") as fh:
        fh.write(b"fila,cortada,por,un,apagado")  # sin salto de línea final
    logger = make_logger(path)
    logger.open()
    logger.write([event(EventType.STATE_CHANGED)])
    logger.close()
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    assert lines[-1].split(",")[6] == "STATE_CHANGED"
    assert lines[-2] == "fila,cortada,por,un,apagado"


def test_record_events_filter(tmp_path):
    path = tmp_path / "events.csv"
    logger = make_logger(path, record={EventType.STATE_CHANGED})
    logger.open()
    logger.write([event(EventType.TEXT_APPEARED), event(EventType.STATE_CHANGED), event(EventType.ERROR)])
    logger.close()
    assert [r["tipo_evento"] for r in read_rows(path)] == ["STATE_CHANGED"]


def test_page_text_cannot_become_an_excel_formula(tmp_path):
    assert excel_safe("=HYPERLINK(\"http://x\")") == "'=HYPERLINK(\"http://x\")"
    assert excel_safe("+1") == "'+1" and excel_safe("@SUM(A1)") == "'@SUM(A1)"
    assert excel_safe("online") == "online"
    path = tmp_path / "events.csv"
    logger = make_logger(path)
    logger.open()
    logger.write([event(excerpt="=1+1")])
    logger.close()
    assert read_rows(path)[0]["extracto_texto"] == "'=1+1"


# 15. Cambio de zona horaria -------------------------------------------------------------

@pytest.mark.parametrize(
    ("tz", "when", "local_iso"),
    [
        ("America/Lima", datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc), "2026-01-15T07:00:00.000-05:00"),
        ("America/Lima", datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc), "2026-07-15T07:00:00.000-05:00"),
        ("Europe/Madrid", datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc), "2026-01-15T13:00:00.000+01:00"),
        ("Europe/Madrid", datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc), "2026-07-15T14:00:00.000+02:00"),
        ("UTC", datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc), "2026-07-15T12:00:00.000+00:00"),
    ],
)
def test_local_time_follows_configured_timezone(tmp_path, tz, when, local_iso):
    path = tmp_path / "events.csv"
    logger = make_logger(path, tz=tz)
    logger.open()
    logger.write([event(when=when)])
    logger.close()
    row = read_rows(path)[0]
    assert row["fecha_hora_local"] == local_iso
    assert row["fecha_hora_utc"] == when.isoformat(timespec="milliseconds")
    assert row["zona_horaria"] == tz


def test_local_date_changes_at_local_midnight(tmp_path):
    # 03:30 UTC del día 15 sigue siendo el día 14 en Lima.
    path = tmp_path / "events.csv"
    logger = make_logger(path)
    logger.open()
    logger.write([event(when=datetime(2026, 10, 15, 3, 30, tzinfo=timezone.utc))])
    logger.close()
    row = read_rows(path)[0]
    assert (row["fecha_local"], row["hora_local"]) == ("2026-10-14", "22:30:00")
