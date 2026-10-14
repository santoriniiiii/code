"""Carga y validación de la configuración (archivo TOML).

Toda la configuración se valida antes de empezar: si hay errores se muestran
todos juntos y el programa no arranca. Las rutas relativas se interpretan
respecto a la carpeta donde está el archivo de configuración.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .models import PERSISTABLE_EVENT_TYPES, EventType


class ConfigError(Exception):
    """Configuración inválida. `problems` contiene un mensaje por problema."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


@dataclass(frozen=True)
class PageConfig:
    url: str
    label: str


@dataclass(frozen=True)
class ExtractionConfig:
    method: str  # "browser" | "http"
    selector: str
    frame_selectors: tuple[str, ...]
    match_policy: str  # "single" | "first" | "all"
    text_source: str  # "visible" | "all"
    element_missing: str  # "unknown" | "absent"
    reload_each_check: bool
    wait_until: str
    page_load_timeout_s: float
    element_timeout_s: float
    settle_s: float


@dataclass(frozen=True)
class BrowserConfig:
    headless: bool
    channel: str
    executable_path: Path | None
    user_data_dir: Path | None


@dataclass(frozen=True)
class HttpConfig:
    timeout_s: float
    user_agent: str


@dataclass(frozen=True)
class TargetConfig:
    id: str
    text: str
    mode: str  # "contains" | "word" | "exact" | "regex"
    state: str
    case_sensitive: bool


@dataclass(frozen=True)
class MatchingConfig:
    case_sensitive: bool
    whitespace: str  # "collapse" | "strip" | "exact"
    multiple_states: str  # "priority" | "conflict" | "combined"
    no_match: str  # "state" | "unknown"
    no_match_state: str
    excerpt_max_chars: int


@dataclass(frozen=True)
class ConfirmationConfig:
    required_observations: int
    unknown_policy: str  # "ignore" | "reset"
    rebaseline_after_failures: int
    resume_state: bool


@dataclass(frozen=True)
class ScheduleConfig:
    interval_s: float
    backoff_max_s: float
    max_consecutive_errors: int


@dataclass(frozen=True)
class OutputConfig:
    csv_path: Path
    csv_delimiter: str
    state_path: Path
    log_path: Path
    log_level: str
    timezone: str
    record_events: frozenset[EventType]
    terminal: str  # "quiet" | "normal" | "verbose"


@dataclass(frozen=True)
class AppConfig:
    page: PageConfig
    extraction: ExtractionConfig
    browser: BrowserConfig
    http: HttpConfig
    targets: tuple[TargetConfig, ...]
    matching: MatchingConfig
    confirmation: ConfirmationConfig
    schedule: ScheduleConfig
    output: OutputConfig
    source_path: Path | None = None
    warnings: tuple[str, ...] = ()

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.output.timezone)

    def fingerprint(self) -> str:
        """Huella de los ajustes que definen QUÉ se observa.

        Si cambia (otra URL, otro selector, otros textos...), el estado
        guardado de una ejecución anterior ya no es comparable y no se reutiliza.
        """
        relevant = {
            "url": self.page.url,
            "method": self.extraction.method,
            "selector": self.extraction.selector,
            "frames": list(self.extraction.frame_selectors),
            "match_policy": self.extraction.match_policy,
            "text_source": self.extraction.text_source,
            "element_missing": self.extraction.element_missing,
            "matching": {
                "case_sensitive": self.matching.case_sensitive,
                "whitespace": self.matching.whitespace,
                "multiple_states": self.matching.multiple_states,
                "no_match": self.matching.no_match,
                "no_match_state": self.matching.no_match_state,
            },
            "targets": [
                [t.id, t.text, t.mode, t.state, t.case_sensitive] for t in self.targets
            ],
        }
        data = json.dumps(relevant, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(data).hexdigest()[:16]


# --------------------------------------------------------------------------
# Lectura con validación
# --------------------------------------------------------------------------

_REQUIRED = object()
_TYPE_NAMES = {str: "un texto", bool: "true o false", int: "un número entero", float: "un número", list: "una lista"}

METHODS = ("browser", "http")
MATCH_POLICIES = ("single", "first", "all")
TEXT_SOURCES = ("visible", "all")
ELEMENT_MISSING = ("unknown", "absent")
WAIT_UNTIL = ("load", "domcontentloaded", "networkidle", "commit")
CHANNELS = ("", "chromium", "chrome", "chrome-beta", "chrome-dev", "chrome-canary",
            "msedge", "msedge-beta", "msedge-dev", "msedge-canary")
TARGET_MODES = ("contains", "word", "exact", "regex")
WHITESPACE = ("collapse", "strip", "exact")
MULTIPLE_STATES = ("priority", "conflict", "combined")
NO_MATCH = ("state", "unknown")
UNKNOWN_POLICIES = ("ignore", "reset")
DELIMITERS = (",", ";", "\t")
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
TERMINAL = ("quiet", "normal", "verbose")
SECTIONS = ("page", "extraction", "browser", "http", "matching", "targets",
            "confirmation", "schedule", "errors", "output")

_ID_RE = re.compile(r"^[\w.-]+$")


class _Section:
    def __init__(self, data: Any, name: str, problems: list[str]):
        self.name = name
        self.problems = problems
        self.used: set[str] = set()
        if data is None:
            data = {}
        if not isinstance(data, dict):
            problems.append(f"[{name}] debe ser una sección (tabla TOML)")
            data = {}
        self.data: dict[str, Any] = data

    def has(self, key: str) -> bool:
        return key in self.data

    def get(self, key: str, typ: type, default: Any = _REQUIRED, *, choices: tuple | None = None,
            minimum: float | None = None, maximum: float | None = None) -> Any:
        self.used.add(key)
        if key not in self.data:
            if default is _REQUIRED:
                self.problems.append(f"[{self.name}] falta la clave obligatoria '{key}'")
                return None
            return default
        value = self.data[key]
        if typ is float and isinstance(value, int) and not isinstance(value, bool):
            value = float(value)
        wrong_type = not isinstance(value, typ) or (typ in (int, float) and isinstance(value, bool))
        if wrong_type:
            self.problems.append(
                f"[{self.name}] '{key}' debe ser {_TYPE_NAMES.get(typ, typ.__name__)}; se recibió {value!r}"
            )
            return None if default is _REQUIRED else default
        if choices is not None and value not in choices:
            opciones = ", ".join(repr(c) for c in choices)
            self.problems.append(f"[{self.name}] '{key}' = {value!r} no es válido; opciones: {opciones}")
            return None if default is _REQUIRED else default
        if minimum is not None and value < minimum:
            self.problems.append(f"[{self.name}] '{key}' debe ser como mínimo {minimum}; se recibió {value}")
        if maximum is not None and value > maximum:
            self.problems.append(f"[{self.name}] '{key}' debe ser como máximo {maximum}; se recibió {value}")
        return value

    def get_str_list(self, key: str, default: list[str]) -> list[str]:
        value = self.get(key, list, default)
        if value is None:
            return list(default)
        if not all(isinstance(v, str) and v.strip() for v in value):
            self.problems.append(f"[{self.name}] '{key}' debe ser una lista de textos no vacíos")
            return list(default)
        return list(value)

    def finish(self) -> None:
        for key in sorted(set(self.data) - self.used):
            self.problems.append(f"[{self.name}] clave desconocida '{key}' (¿error de escritura?)")


def _resolve_path(raw: str, base: Path) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else base / path


def normalize_for_comparison(text: str, whitespace: str) -> str:
    """Normalización Unicode y de espacios usada en toda la aplicación."""
    text = unicodedata.normalize("NFC", text)
    if whitespace == "collapse":
        text = re.sub("[​⁠﻿­]", "", text)  # caracteres invisibles
        return " ".join(text.split())
    if whitespace == "strip":
        return text.strip()
    return text


def load_config(path: str | Path) -> AppConfig:
    """Lee y valida un archivo TOML. Lanza ConfigError con todos los problemas."""
    path = Path(path).expanduser()
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except FileNotFoundError:
        raise ConfigError([f"No existe el archivo de configuración: {path}"]) from None
    except PermissionError:
        raise ConfigError([f"Sin permiso para leer el archivo de configuración: {path}"]) from None
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError([f"Error de sintaxis TOML en {path}: {exc}"]) from None
    return parse_config(raw, base_dir=path.resolve().parent, source_path=path.resolve())


def parse_config(raw: dict[str, Any], base_dir: Path, source_path: Path | None = None) -> AppConfig:
    problems: list[str] = []
    warnings: list[str] = []

    for key in sorted(set(raw) - set(SECTIONS)):
        problems.append(f"Sección desconocida [{key}] (¿error de escritura?)")

    # [page] ------------------------------------------------------------------
    s = _Section(raw.get("page"), "page", problems)
    url = s.get("url", str)
    label = s.get("label", str, "")
    s.finish()

    # [extraction] ------------------------------------------------------------
    s = _Section(raw.get("extraction"), "extraction", problems)
    method = s.get("method", str, "browser", choices=METHODS)
    selector = s.get("selector", str)
    frame_selectors = s.get_str_list("frame_selectors", [])
    match_policy = s.get("match_policy", str, "single", choices=MATCH_POLICIES)
    text_source_explicit = s.has("text_source")
    text_source = s.get("text_source", str, "visible", choices=TEXT_SOURCES)
    element_missing = s.get("element_missing", str, "unknown", choices=ELEMENT_MISSING)
    reload_each_check = s.get("reload_each_check", bool, True)
    wait_until = s.get("wait_until", str, "load", choices=WAIT_UNTIL)
    page_load_timeout = s.get("page_load_timeout_seconds", float, 30.0, minimum=1, maximum=600)
    element_timeout = s.get("element_timeout_seconds", float, 10.0, minimum=0.1, maximum=600)
    settle = s.get("settle_seconds", float, 0.0, minimum=0, maximum=60)
    s.finish()

    # [browser] ---------------------------------------------------------------
    s = _Section(raw.get("browser"), "browser", problems)
    headless = s.get("headless", bool, True)
    channel = s.get("channel", str, "", choices=CHANNELS)
    executable_path_raw = s.get("executable_path", str, "")
    user_data_dir_raw = s.get("user_data_dir", str, "")
    s.finish()

    # [http] ------------------------------------------------------------------
    s = _Section(raw.get("http"), "http", problems)
    http_timeout = s.get("timeout_seconds", float, 20.0, minimum=1, maximum=600)
    user_agent = s.get("user_agent", str, "")
    s.finish()

    # [matching] --------------------------------------------------------------
    s = _Section(raw.get("matching"), "matching", problems)
    case_sensitive = s.get("case_sensitive", bool, False)
    whitespace = s.get("whitespace", str, "collapse", choices=WHITESPACE)
    multiple_states = s.get("multiple_states", str, "conflict", choices=MULTIPLE_STATES)
    no_match = s.get("no_match", str, "state", choices=NO_MATCH)
    no_match_state = s.get("no_match_state", str, "sin_coincidencia")
    excerpt_max_chars = s.get("excerpt_max_chars", int, 200, minimum=0, maximum=5000)
    s.finish()

    # [[targets]] -------------------------------------------------------------
    targets: list[TargetConfig] = []
    raw_targets = raw.get("targets")
    if not isinstance(raw_targets, list) or not raw_targets:
        problems.append("Define al menos un texto de interés con una sección [[targets]]")
        raw_targets = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw_targets, start=1):
        t = _Section(item, f"targets #{index}", problems)
        tid = t.get("id", str)
        text = t.get("text", str)
        mode = t.get("mode", str, "contains", choices=TARGET_MODES)
        state = t.get("state", str, tid or "")
        t_case = t.get("case_sensitive", bool, case_sensitive)
        t.finish()
        if tid is None or text is None:
            continue
        if not _ID_RE.match(tid):
            problems.append(f"[targets #{index}] 'id' solo admite letras, números, '_', '.' y '-': {tid!r}")
        if tid in seen_ids:
            problems.append(f"[targets #{index}] el id {tid!r} está repetido")
        seen_ids.add(tid)
        if not normalize_for_comparison(text, whitespace or "collapse"):
            problems.append(f"[targets #{index}] 'text' no puede estar vacío")
        if not state or not state.strip():
            problems.append(f"[targets #{index}] 'state' no puede estar vacío")
        elif "+" in state:
            problems.append(f"[targets #{index}] 'state' no puede contener '+': {state!r}")
        if mode == "regex":
            try:
                compiled = re.compile(text, 0 if t_case else re.IGNORECASE)
            except re.error as exc:
                problems.append(f"[targets #{index}] expresión regular no válida {text!r}: {exc}")
            else:
                if compiled.search("") is not None:
                    problems.append(
                        f"[targets #{index}] la expresión regular {text!r} coincide con un texto vacío; "
                        "siempre se consideraría presente"
                    )
        targets.append(TargetConfig(id=tid, text=text, mode=mode, state=state, case_sensitive=t_case))

    # [confirmation] ----------------------------------------------------------
    s = _Section(raw.get("confirmation"), "confirmation", problems)
    required = s.get("required_observations", int, 2, minimum=1, maximum=100)
    unknown_policy = s.get("unknown_policy", str, "ignore", choices=UNKNOWN_POLICIES)
    rebaseline_after = s.get("rebaseline_after_failures", int, 0, minimum=0)
    resume_state = s.get("resume_state", bool, True)
    s.finish()

    # [schedule] y [errors] ---------------------------------------------------
    s = _Section(raw.get("schedule"), "schedule", problems)
    interval = s.get("interval_seconds", float, 5.0, minimum=1, maximum=86_400)
    s.finish()
    s = _Section(raw.get("errors"), "errors", problems)
    backoff_max = s.get("backoff_max_seconds", float, 60.0, minimum=1, maximum=86_400)
    max_errors = s.get("max_consecutive_errors", int, 120, minimum=0)
    s.finish()

    # [output] ----------------------------------------------------------------
    s = _Section(raw.get("output"), "output", problems)
    csv_path = s.get("csv_path", str, "data/events.csv")
    csv_delimiter = s.get("csv_delimiter", str, ",", choices=DELIMITERS)
    state_path = s.get("state_path", str, "data/state.json")
    log_path = s.get("log_path", str, "logs/application.log")
    log_level = s.get("log_level", str, "INFO", choices=LOG_LEVELS)
    timezone_name = s.get("timezone", str, "America/Lima")
    record_raw = s.get_str_list("record_events", sorted(e.value for e in PERSISTABLE_EVENT_TYPES))
    terminal = s.get("terminal", str, "normal", choices=TERMINAL)
    s.finish()

    # Validaciones que relacionan varios valores --------------------------------
    if url is not None:
        parsed = urlparse(url)
        allowed = ("http", "https") if method == "http" else ("http", "https", "file")
        if parsed.scheme not in allowed:
            problems.append(f"[page] 'url' debe empezar por {' o '.join(a + '://' for a in allowed)}: {url!r}")
        elif parsed.scheme in ("http", "https") and not parsed.netloc:
            problems.append(f"[page] 'url' no tiene dominio: {url!r}")
    if selector is not None and not selector.strip():
        problems.append("[extraction] 'selector' no puede estar vacío")
    if method == "http":
        if frame_selectors:
            problems.append("[extraction] 'frame_selectors' solo funciona con method = \"browser\"")
        if selector and (selector.startswith(("xpath=", "//", "..", "(")) or ">>" in selector):
            problems.append("[extraction] con method = \"http\" el selector debe ser CSS (XPath y la sintaxis "
                            "propia de Playwright solo funcionan con method = \"browser\")")
        elif selector and selector.strip():
            try:
                import soupsieve

                soupsieve.compile(selector)
            except ImportError:
                pass
            except Exception as exc:  # soupsieve.SelectorSyntaxError
                problems.append(f"[extraction] selector CSS no válido {selector!r}: {str(exc).splitlines()[0]}")
        if text_source_explicit and text_source == "visible":
            warnings.append("text_source = \"visible\" no tiene efecto con method = \"http\": sin navegador no "
                            "se puede evaluar el CSS, así que se lee todo el texto del HTML.")
        if user_data_dir_raw:
            warnings.append("[browser] user_data_dir se ignora con method = \"http\".")
        if settle:
            warnings.append("[extraction] settle_seconds solo tiene efecto con method = \"browser\".")
    if no_match_state is not None:
        if not no_match_state.strip():
            problems.append("[matching] 'no_match_state' no puede estar vacío")
        if "+" in no_match_state:
            problems.append("[matching] 'no_match_state' no puede contener '+'")
        if any(t.state == no_match_state for t in targets):
            problems.append(f"[matching] 'no_match_state' ({no_match_state!r}) coincide con el estado de un texto")
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        problems.append(f"[output] zona horaria desconocida: {timezone_name!r} (ejemplo: \"America/Lima\")")
    record_events: set[EventType] = set()
    for name in record_raw:
        try:
            event_type = EventType(name)
        except ValueError:
            problems.append(f"[output] tipo de evento desconocido en 'record_events': {name!r}")
            continue
        if event_type is EventType.NO_CHANGE:
            problems.append("[output] NO_CHANGE no se puede guardar en el CSV (sería una fila por comprobación)")
            continue
        record_events.add(event_type)
    if backoff_max is not None and interval is not None and backoff_max < interval:
        warnings.append("[errors] backoff_max_seconds es menor que el intervalo; tras un error se esperará el intervalo normal.")
    if interval is not None and interval < 5 and method == "browser" and reload_each_check:
        warnings.append(f"Intervalo de {interval:g} s recargando la página cada vez: comprueba que el sitio lo permite.")

    # Textos que se contienen unos a otros con mode = "contains" (p. ej. "available" / "unavailable")
    for a in targets:
        for b in targets:
            if a is b or a.mode != "contains" or a.state == b.state or b.mode == "regex":
                continue
            na = normalize_for_comparison(a.text, whitespace or "collapse")
            nb = normalize_for_comparison(b.text, whitespace or "collapse")
            if not a.case_sensitive:
                na, nb = na.casefold(), nb.casefold()
            if na and na in nb:
                warnings.append(
                    f"El texto {a.text!r} ({a.id}) está contenido en {b.text!r} ({b.id}): cuando aparezca "
                    f"{b.text!r} también se detectará {a.text!r}. Usa mode = \"word\" o \"exact\" en '{a.id}'."
                )

    if problems:
        raise ConfigError(problems)

    if not label:
        label = urlparse(url).netloc or url

    return AppConfig(
        page=PageConfig(url=url, label=label),
        extraction=ExtractionConfig(
            method=method,
            selector=selector.strip(),
            frame_selectors=tuple(frame_selectors),
            match_policy=match_policy,
            text_source=text_source if method == "browser" else "all",
            element_missing=element_missing,
            reload_each_check=reload_each_check,
            wait_until=wait_until,
            page_load_timeout_s=page_load_timeout,
            element_timeout_s=element_timeout,
            settle_s=settle,
        ),
        browser=BrowserConfig(
            headless=headless,
            channel=channel,
            executable_path=_resolve_path(executable_path_raw, base_dir) if executable_path_raw else None,
            user_data_dir=_resolve_path(user_data_dir_raw, base_dir) if user_data_dir_raw else None,
        ),
        http=HttpConfig(timeout_s=http_timeout, user_agent=user_agent),
        targets=tuple(targets),
        matching=MatchingConfig(
            case_sensitive=case_sensitive,
            whitespace=whitespace,
            multiple_states=multiple_states,
            no_match=no_match,
            no_match_state=no_match_state,
            excerpt_max_chars=excerpt_max_chars,
        ),
        confirmation=ConfirmationConfig(
            required_observations=required,
            unknown_policy=unknown_policy,
            rebaseline_after_failures=rebaseline_after,
            resume_state=resume_state,
        ),
        schedule=ScheduleConfig(interval_s=interval, backoff_max_s=backoff_max, max_consecutive_errors=max_errors),
        output=OutputConfig(
            csv_path=_resolve_path(csv_path, base_dir),
            csv_delimiter=csv_delimiter,
            state_path=_resolve_path(state_path, base_dir),
            log_path=_resolve_path(log_path, base_dir),
            log_level=log_level,
            timezone=timezone_name,
            record_events=frozenset(record_events),
            terminal=terminal,
        ),
        source_path=source_path,
        warnings=tuple(warnings),
    )
