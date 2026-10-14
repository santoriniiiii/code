"""Pruebas de la validación de la configuración."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_config

from textmonitor.config import ConfigError, load_config
from textmonitor.models import EventType

PROJECT = Path(__file__).resolve().parent.parent


def problems(**sections) -> str:
    with pytest.raises(ConfigError) as info:
        make_config(**sections)
    return "\n".join(info.value.problems)


@pytest.mark.parametrize("name", ["config.example.toml", "config.demo.toml"])
def test_shipped_configs_are_valid(name):
    config = load_config(PROJECT / name)
    assert config.schedule.interval_s == 5
    assert config.output.timezone == "America/Lima"
    assert EventType.NO_CHANGE not in config.output.record_events


def test_defaults():
    from textmonitor.config import parse_config

    raw = {"page": {"url": "https://ejemplo.test"}, "extraction": {"selector": "#x"},
           "targets": [{"id": "a", "text": "a"}]}
    config = parse_config(raw, base_dir=Path("/tmp"))
    assert config.extraction.reload_each_check is True
    assert config.extraction.text_source == "visible"
    assert config.matching.case_sensitive is False
    assert config.matching.multiple_states == "conflict"  # nunca se elige un estado arbitrariamente
    assert config.schedule.max_consecutive_errors == 120
    assert config.schedule.interval_s == 5
    assert config.confirmation.required_observations == 2
    assert config.output.timezone == "America/Lima"


def test_relative_paths_are_relative_to_config_folder(tmp_path):
    config = make_config(tmp_path)
    assert config.output.csv_path == tmp_path / "data" / "events.csv"
    assert config.output.log_path == tmp_path / "logs" / "app.log"


def test_missing_file_and_bad_syntax(tmp_path):
    with pytest.raises(ConfigError, match="No existe"):
        load_config(tmp_path / "no_existe.toml")
    bad = tmp_path / "mala.toml"
    bad.write_text("[page\nurl = 'x'", encoding="utf-8")
    with pytest.raises(ConfigError, match="sintaxis TOML"):
        load_config(bad)


def test_typo_in_key_is_reported():
    assert "clave desconocida 'intervalo'" in problems(schedule={"intervalo": 5})


def test_unknown_section_is_reported():
    assert "Sección desconocida [extration]" in problems(extration={"selector": "#x"})


def test_wrong_types_and_ranges():
    text = problems(schedule={"interval_seconds": "5"}, confirmation={"required_observations": 0})
    assert "'interval_seconds' debe ser un número" in text
    assert "'required_observations' debe ser como mínimo 1" in text
    assert "debe ser como mínimo 1" in problems(schedule={"interval_seconds": 0.5})


def test_bool_is_not_accepted_as_number():
    assert "debe ser un número" in problems(schedule={"interval_seconds": True})


def test_invalid_choice():
    assert "opciones" in problems(extraction={"method": "selenium"})


def test_invalid_url():
    assert "'url' debe empezar por" in problems(page={"url": "ejemplo.com"})


def test_invalid_timezone():
    assert "zona horaria desconocida" in problems(output={"timezone": "Lima"})


def test_target_validation():
    text = problems(targets=[
        {"id": "a", "text": "uno"},
        {"id": "a", "text": "   "},
        {"id": "b c", "text": "(", "mode": "regex"},
        {"id": "d", "text": "x*", "mode": "regex"},
    ])
    assert "repetido" in text
    assert "'text' no puede estar vacío" in text
    assert "solo admite letras" in text
    assert "expresión regular no válida" in text
    assert "coincide con un texto vacío" in text


def test_no_targets():
    assert "al menos un texto" in problems(targets=[])


def test_no_match_state_cannot_collide_with_target_state():
    assert "coincide con el estado de un texto" in problems(matching={"no_match_state": "online"})


def test_http_method_limits():
    text = problems(extraction={"method": "http", "selector": "xpath=//div", "frame_selectors": ["iframe"]})
    assert "frame_selectors" in text and "debe ser CSS" in text
    assert "selector CSS no válido" in problems(extraction={"method": "http", "selector": "div[["})


def test_no_change_cannot_be_recorded():
    assert "NO_CHANGE no se puede guardar" in problems(output={"record_events": ["NO_CHANGE"]})


def test_fingerprint_depends_on_what_is_observed_not_on_interval():
    base = make_config()
    assert base.fingerprint() == make_config(schedule={"interval_seconds": 30}).fingerprint()
    assert base.fingerprint() != make_config(extraction={"selector": "#otro"}).fingerprint()
    changed_targets = [{"id": "online", "text": "conectado"}, {"id": "offline", "text": "offline"}]
    assert base.fingerprint() != make_config(targets=changed_targets).fingerprint()


def test_all_problems_reported_together():
    with pytest.raises(ConfigError) as info:
        make_config(page={"url": "x"}, schedule={"interval_seconds": 0}, output={"timezone": "Nada/Nada"})
    assert len(info.value.problems) >= 3
