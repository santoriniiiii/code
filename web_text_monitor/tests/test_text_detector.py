"""Pruebas del detector: qué textos están presentes y qué estado representan."""

from __future__ import annotations

from conftest import error, make_config, missing, obs

from textmonitor.models import ObservationKind
from textmonitor.text_detector import TextDetector


def interpret(*texts, **sections):
    return TextDetector(make_config(**sections)).interpret(obs(*texts))


# --- Mayúsculas y minúsculas (prueba 13) -------------------------------------------------

def test_insensitive_by_default_and_keeps_page_spelling():
    result = interpret("Estado: ONLINE")
    assert result.kind is ObservationKind.VALID
    assert result.snapshot.state == "online"
    assert result.snapshot.match_for("online") == "ONLINE"  # se guarda tal como aparece


def test_case_sensitive_global():
    result = interpret("Estado: ONLINE", matching={"case_sensitive": True})
    assert result.snapshot.state == "sin_coincidencia"
    assert interpret("online", matching={"case_sensitive": True}).snapshot.state == "online"


def test_case_sensitive_per_target_overrides_global():
    targets = [
        {"id": "ok", "text": "OK", "mode": "word", "case_sensitive": True},
        {"id": "fallo", "text": "fallo", "mode": "word"},
    ]
    assert interpret("ok", targets=targets).snapshot.state == "sin_coincidencia"
    assert interpret("OK", targets=targets).snapshot.state == "ok"
    assert interpret("FALLO", targets=targets).snapshot.state == "fallo"


# --- Espacios en blanco ----------------------------------------------------------------------

def test_whitespace_collapse_handles_newlines_tabs_nbsp_and_zero_width():
    targets = [{"id": "linea", "text": "en  línea", "mode": "contains"}]
    assert interpret("Estado:\n\ten lí​nea  ", targets=targets).snapshot.state == "linea"


def test_whitespace_exact_requires_identical_spacing():
    targets = [{"id": "linea", "text": "en línea", "mode": "contains"}]
    result = interpret("en\nlínea", targets=targets, matching={"whitespace": "exact"})
    assert result.snapshot.state == "sin_coincidencia"


def test_unicode_normalization_nfc():
    # "í" compuesto (U+00ED) frente a "i" + acento combinante (U+0069 U+0301)
    targets = [{"id": "linea", "text": "en línea", "mode": "contains"}]
    assert interpret("en línea", targets=targets).snapshot.state == "linea"


# --- Modos de coincidencia -----------------------------------------------------------------

def test_word_mode_avoids_substring_trap():
    targets = [
        {"id": "available", "text": "available", "mode": "word"},
        {"id": "unavailable", "text": "unavailable", "mode": "word"},
    ]
    assert interpret("Product unavailable", targets=targets).snapshot.state == "unavailable"
    assert interpret("Product available", targets=targets).snapshot.state == "available"


def test_contains_mode_substring_produces_conflict_and_config_warning():
    targets = [
        {"id": "available", "text": "available", "mode": "contains"},
        {"id": "unavailable", "text": "unavailable", "mode": "contains"},
    ]
    config = make_config(targets=targets)
    assert any("contenido en" in w for w in config.warnings)
    result = TextDetector(config).interpret(obs("Product unavailable"))
    assert result.kind is ObservationKind.UNKNOWN  # multiple_states = "conflict"


def test_exact_mode_compares_whole_element_text():
    targets = [{"id": "online", "text": "online", "mode": "exact"}]
    assert interpret("  Online \n", targets=targets).snapshot.state == "online"
    assert interpret("online desde las 10:00", targets=targets).snapshot.state == "sin_coincidencia"


def test_regex_mode():
    targets = [{"id": "pedido", "text": r"pedido\s+#\d+", "mode": "regex"}]
    result = interpret("Último: Pedido   #4521 enviado", targets=targets)
    assert result.snapshot.state == "pedido"
    assert result.snapshot.match_for("pedido") == "Pedido #4521"


# --- Varios textos a la vez (prueba 14) ----------------------------------------------------

def test_multiple_states_conflict_is_unknown():
    result = interpret("online / offline")
    assert result.kind is ObservationKind.UNKNOWN
    assert "varios estados" in result.reason


def test_multiple_states_priority_uses_config_order():
    result = interpret("offline ... online", matching={"multiple_states": "priority"})
    assert result.snapshot.state == "online"  # "online" está antes en [[targets]]
    assert result.snapshot.present == frozenset({"online", "offline"})


def test_multiple_states_combined():
    result = interpret("offline ... online", matching={"multiple_states": "combined"})
    assert result.snapshot.state == "online+offline"


def test_synonyms_map_to_same_state_without_conflict():
    targets = [
        {"id": "online", "text": "online", "mode": "word"},
        {"id": "en_linea", "text": "en línea", "mode": "contains", "state": "online"},
        {"id": "offline", "text": "offline", "mode": "word"},
    ]
    result = interpret("online (en línea)", targets=targets)
    assert result.kind is ObservationKind.VALID
    assert result.snapshot.state == "online"
    assert result.snapshot.present == frozenset({"online", "en_linea"})


# --- Ausencia de texto, elemento ausente y errores -------------------------------------------

def test_no_target_present_gives_no_match_state():
    result = interpret("mantenimiento programado")
    assert result.snapshot.state == "sin_coincidencia"
    assert result.snapshot.present == frozenset()
    assert result.excerpt == "mantenimiento programado"


def test_no_target_present_can_be_unknown():
    result = interpret("mantenimiento", matching={"no_match": "unknown"})
    assert result.kind is ObservationKind.UNKNOWN


def test_hidden_element_is_read_as_empty_text_which_means_absent():
    # El extractor del navegador entrega "" para un elemento oculto (text_source = "visible").
    assert interpret("").snapshot.state == "sin_coincidencia"


def test_element_missing_is_unknown_by_default():
    result = TextDetector(make_config()).interpret(missing())
    assert result.kind is ObservationKind.UNKNOWN
    assert "elemento no encontrado" in result.reason


def test_element_missing_can_mean_absent():
    detector = TextDetector(make_config(extraction={"element_missing": "absent"}))
    result = detector.interpret(missing())
    assert result.kind is ObservationKind.VALID
    assert result.snapshot.state == "sin_coincidencia"


def test_read_error_is_error_not_absence():
    result = TextDetector(make_config()).interpret(error())
    assert result.kind is ObservationKind.ERROR
    assert result.snapshot is None


# --- Varios elementos que coinciden con el selector ------------------------------------------

def test_match_policy_single_rejects_several_elements():
    result = interpret("online", "offline")
    assert result.kind is ObservationKind.UNKNOWN
    assert "2 elementos" in result.reason


def test_match_policy_first():
    result = interpret("offline", "online", extraction={"match_policy": "first"})
    assert result.snapshot.state == "offline"


def test_match_policy_all_with_exact_checks_each_element():
    targets = [{"id": "agotado", "text": "Agotado", "mode": "exact"}]
    result = interpret("Disponible", "Agotado", "Disponible", targets=targets, extraction={"match_policy": "all"})
    assert result.snapshot.state == "agotado"


# --- Extracto -------------------------------------------------------------------------------

def test_excerpt_is_truncated_and_can_be_disabled():
    long_text = "online " + "x" * 500
    assert len(interpret(long_text, matching={"excerpt_max_chars": 50}).excerpt) == 50
    assert interpret(long_text, matching={"excerpt_max_chars": 0}).excerpt == ""
