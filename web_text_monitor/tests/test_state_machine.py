"""Pruebas de la máquina de estados con observaciones simuladas (sin red)."""

from __future__ import annotations

from datetime import timedelta

from conftest import T0, Pipeline, error, make_config, missing, obs

from textmonitor.models import ConfirmedState, EventType, Outcome
from textmonitor.state_store import StateStore


def P(**sections) -> Pipeline:
    return Pipeline(make_config(**sections))


# 1. Texto presente desde la primera observación ------------------------------------------

def test_text_present_from_first_observation_only_sets_baseline():
    p = P()
    p.feed_texts("online", "online", "online")
    assert p.types() == ["BASELINE"]
    baseline = p.events[0]
    assert baseline.new_state == "online"
    assert baseline.previous_state == ""  # no se inventa un estado anterior
    assert "línea base inicial" in baseline.detail
    assert [r.outcome for r in p.results] == [Outcome.BASELINE, Outcome.NO_CHANGE, Outcome.NO_CHANGE]


def test_baseline_with_confirmation_needs_n_equal_observations():
    p = P(confirmation={"required_observations": 2})
    results = p.feed_texts("online", "online")
    assert [r.outcome for r in results] == [Outcome.BASELINE_PENDING, Outcome.BASELINE]
    assert p.events[0].confirmations == 2
    assert p.events[0].first_seen_new_utc == T0


# 2. Aparición de un texto ------------------------------------------------------------------

def test_text_appears():
    p = P()
    p.feed_texts("cargado", "online")
    assert p.types() == ["BASELINE", "TEXT_APPEARED", "STATE_CHANGED"]
    appeared = p.events[1]
    assert appeared.searched_text == "online"
    assert appeared.new_text == "online"
    assert appeared.previous_text == ""
    change = p.events[2]
    assert (change.previous_state, change.new_state) == ("sin_coincidencia", "online")


# 3. Desaparición de un texto ---------------------------------------------------------------

def test_text_disappears():
    p = P()
    p.feed_texts("online", "")
    assert p.types() == ["BASELINE", "TEXT_DISAPPEARED", "STATE_CHANGED"]
    disappeared = p.events[1]
    assert disappeared.previous_text == "online"
    assert disappeared.new_text == ""
    assert p.events[2].new_state == "sin_coincidencia"


# 4. Sustitución de un texto por otro -------------------------------------------------------

def test_text_replaced_by_another():
    p = P()
    p.feed_texts("Estado: Online", "Estado: Offline")
    assert p.types() == ["BASELINE", "TEXT_DISAPPEARED", "TEXT_APPEARED", "STATE_CHANGED"]
    transition = p.events[1:]
    assert len({e.transition_id for e in transition}) == 1  # mismas filas, mismo cambio
    change = p.events[-1]
    assert (change.previous_state, change.new_state) == ("online", "offline")
    assert (change.previous_text, change.new_text) == ("Online", "Offline")
    assert change.last_seen_previous_utc == T0
    assert change.first_seen_new_utc == T0 + timedelta(seconds=5)
    assert "el cambio ocurrió entre" in change.detail


def test_replacement_by_unconfigured_text_keeps_excerpt():
    p = P()
    p.feed_texts("online", "mantenimiento")
    change = p.events[-1]
    assert change.new_state == "sin_coincidencia"
    assert change.excerpt == "mantenimiento"


# 5. Ausencia de cambios --------------------------------------------------------------------

def test_no_change_produces_no_events():
    p = P()
    p.feed_texts(*["online"] * 20)
    assert p.types() == ["BASELINE"]
    assert all(r.outcome is Outcome.NO_CHANGE for r in p.results[1:])


# 6. Dos observaciones consecutivas del mismo estado ----------------------------------------

def test_change_confirmed_after_two_consecutive_observations():
    p = P(confirmation={"required_observations": 2})
    results = p.feed_texts("online", "online", "offline", "offline")
    assert [r.outcome for r in results] == [
        Outcome.BASELINE_PENDING, Outcome.BASELINE, Outcome.CHANGE_PENDING, Outcome.CHANGED,
    ]
    change = p.events[-1]
    assert change.confirmations == 2
    assert change.first_seen_new_utc == T0 + timedelta(seconds=10)  # primera vez que se vio "offline"
    assert change.timestamp_utc == T0 + timedelta(seconds=15)  # momento de la confirmación


def test_single_flicker_is_filtered():
    p = P(confirmation={"required_observations": 2})
    p.feed_texts("online", "online", "offline", "online", "online")
    assert p.types() == ["BASELINE"]


def test_alternating_candidates_restart_the_count():
    targets = [{"id": x, "text": x, "mode": "word"} for x in ("rojo", "verde", "azul")]
    p = P(targets=targets, confirmation={"required_observations": 2})
    results = p.feed_texts("rojo", "rojo", "verde", "azul", "azul")
    assert [r.outcome for r in results][-3:] == [Outcome.CHANGE_PENDING, Outcome.CHANGE_PENDING, Outcome.CHANGED]
    assert p.events[-1].new_state == "azul"


# 7. Lectura desconocida -------------------------------------------------------------------

def test_unknown_reading_keeps_state_and_is_recorded_once():
    p = P()
    p.feed_texts("online", missing(t=5), missing(t=10), missing(t=15), "online", start=0)
    assert p.types() == ["BASELINE", "UNKNOWN", "RECOVERED"]
    assert p.events[1].previous_state == "online"
    assert p.machine.confirmed.snapshot.state == "online"
    assert "3 observaciones no válidas" in p.events[2].detail


def test_unknown_policy_ignore_keeps_pending_count():
    p = P(confirmation={"required_observations": 2, "unknown_policy": "ignore"})
    p.feed_texts("online", "online", "offline", missing(t=15), "offline")
    assert "STATE_CHANGED" in p.types()


def test_unknown_policy_reset_requires_strictly_consecutive_observations():
    p = P(confirmation={"required_observations": 2, "unknown_policy": "reset"})
    p.feed_texts("online", "online", "offline", missing(t=15), "offline")
    assert "STATE_CHANGED" not in p.types()
    p.feed(obs("offline", t=25))
    assert p.types()[-1] == "STATE_CHANGED"


# 8. Error de conexión -------------------------------------------------------------------

def test_connection_error_is_not_a_disappearance():
    p = P()
    p.feed_texts("online", error(t=5), error(t=10))
    assert p.types() == ["BASELINE", "ERROR"]
    assert "TEXT_DISAPPEARED" not in p.types()
    assert p.machine.confirmed.snapshot.state == "online"
    assert p.results[-1].outcome is Outcome.ERROR


def test_error_before_any_baseline_does_not_create_state():
    p = P()
    p.feed_texts(error(t=0), error(t=5), "online")
    assert p.types() == ["ERROR", "RECOVERED", "BASELINE"]


# 10. Reinicio del programa -----------------------------------------------------------------

def test_restart_with_same_state_records_nothing(tmp_path):
    config = make_config(tmp_path)
    store = StateStore(tmp_path / "state.json", config.fingerprint())
    first = Pipeline(config)
    first.feed_texts("online", "online")
    store.save(first.machine.confirmed)

    second = Pipeline(config)
    restored, message = store.load()
    assert restored is not None and "restaurado" in message
    second.machine.restore(restored)
    second.feed(obs("online", t=600))
    assert second.types() == []  # ni BASELINE ni cambio duplicado


def test_restart_detects_change_that_happened_while_stopped(tmp_path):
    config = make_config(tmp_path)
    store = StateStore(tmp_path / "state.json", config.fingerprint())
    first = Pipeline(config)
    first.feed_texts("online", "online")
    store.save(first.machine.confirmed)

    second = Pipeline(config)
    second.machine.restore(store.load()[0])
    second.feed(obs("offline", t=3600))
    change = second.events[-1]
    assert change.event_type is EventType.STATE_CHANGED
    assert change.last_seen_previous_utc == T0 + timedelta(seconds=5)
    assert change.first_seen_new_utc == T0 + timedelta(seconds=3600)
    assert "ejecución previa" in change.detail


def test_restart_ignores_state_saved_with_other_configuration(tmp_path):
    old = make_config(tmp_path)
    StateStore(tmp_path / "state.json", old.fingerprint()).save(
        ConfirmedState(snapshot=Pipeline(old).detector.interpret(obs("online")).snapshot, since_utc=T0, last_seen_utc=T0)
    )
    new = make_config(tmp_path, extraction={"selector": "#otro"})
    restored, message = StateStore(tmp_path / "state.json", new.fingerprint()).load()
    assert restored is None
    assert "configuración" in message


def test_corrupt_state_file_is_ignored(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{ esto no es json", encoding="utf-8")
    restored, message = StateStore(path, "x").load()
    assert restored is None and "no se pudo leer" in message


# 11. Recuperación después de una interrupción ---------------------------------------------

def test_recovery_keeps_baseline_and_reports_change_window():
    p = P()
    p.feed_texts("online", error(t=5), error(t=10), error(t=15), "offline", start=0)
    assert p.types() == ["BASELINE", "ERROR", "RECOVERED", "TEXT_DISAPPEARED", "TEXT_APPEARED", "STATE_CHANGED"]
    change = p.events[-1]
    assert change.last_seen_previous_utc == T0
    assert change.first_seen_new_utc == T0 + timedelta(seconds=20)


def test_recovery_with_rebaseline_policy_records_new_baseline_not_a_change():
    p = P(confirmation={"rebaseline_after_failures": 3})
    p.feed_texts("online", error(t=5), error(t=10), error(t=15), "offline", start=0)
    assert p.types() == ["BASELINE", "ERROR", "RECOVERED", "BASELINE"]
    assert p.results[3].baseline_dropped
    assert "restablecida" in p.events[-1].detail and "'online'" in p.events[-1].detail


# 12. Prevención de eventos duplicados -------------------------------------------------------

def test_no_duplicate_events_over_long_sequence():
    p = P(confirmation={"required_observations": 2})
    sequence = (["online"] * 10 + [error(t=0)] * 5 + ["online"] * 10 + ["offline"] * 10
                + [missing(t=0)] * 3 + ["offline"] * 5)
    p.feed_texts(*sequence)
    assert p.types() == [
        "BASELINE", "ERROR", "RECOVERED",
        "TEXT_DISAPPEARED", "TEXT_APPEARED", "STATE_CHANGED",
        "UNKNOWN", "RECOVERED",
    ]


def test_event_ids_are_unique():
    p = P()
    p.feed_texts("online", "offline", "online", "offline")
    ids = [e.event_id for e in p.events]
    assert len(ids) == len(set(ids))


# 14. Varios textos presentes al mismo tiempo (estados independientes) ----------------------

def test_independent_texts_with_combined_policy():
    targets = [
        {"id": "agotado", "text": "Agotado", "mode": "word"},
        {"id": "oferta", "text": "Oferta", "mode": "word"},
    ]
    p = P(targets=targets, matching={"multiple_states": "combined"})
    p.feed_texts("Agotado", "Agotado - Oferta", "Oferta")
    assert p.types() == [
        "BASELINE",
        "TEXT_APPEARED", "STATE_CHANGED",  # agotado -> agotado+oferta
        "TEXT_DISAPPEARED", "STATE_CHANGED",  # agotado+oferta -> oferta
    ]
    assert p.events[2].new_state == "agotado+oferta"


def test_conflicting_texts_never_confirm_a_change():
    p = P()
    p.feed_texts("online", "online offline", "online offline", "online")
    assert p.types() == ["BASELINE", "UNKNOWN", "RECOVERED"]
