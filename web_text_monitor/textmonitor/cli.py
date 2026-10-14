"""Comandos de terminal: run, check, probe, login y demo-server."""

from __future__ import annotations

import argparse
import os
import signal
import sys
import uuid
from pathlib import Path

from . import APP_NAME, __version__
from .config import AppConfig, ConfigError, load_config

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_DIR / "config.toml"


def _load(path: str) -> AppConfig | None:
    try:
        return load_config(path)
    except ConfigError as exc:
        print(f"La configuración {path} no es válida:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        if not Path(path).exists() and Path(path).name == "config.toml":
            print("\nCrea tu configuración a partir del ejemplo:\n    cp config.example.toml config.toml",
                  file=sys.stderr)
        return None


def _write_now(text: str) -> None:
    """Escritura directa (sin búfer): segura dentro de un manejador de señales."""
    try:
        os.write(sys.stdout.fileno(), text.encode("utf-8", "replace"))
    except (OSError, ValueError):
        pass


def cmd_run(args: argparse.Namespace) -> int:
    config = _load(args.config)
    if config is None:
        return 2

    from .app_logging import setup_logging
    from .console import Console
    from .event_logger import CsvEventLogger, EventLogError
    from .monitor import Monitor
    from .state_machine import StateMachine, TargetInfo
    from .state_store import StateStore
    from .text_detector import TextDetector

    console = Console(config.tz, config.output.terminal)
    console.banner(config, "iniciando…")
    try:
        setup_logging(config.output.log_path, config.output.log_level, config.tz)
    except OSError as exc:
        console.say(f"ERROR: no se pudo crear el log {config.output.log_path}: {exc}")
        return 2

    session_id = str(uuid.uuid4())
    event_logger = CsvEventLogger(
        config.output.csv_path,
        timezone=config.output.timezone,
        page_label=config.page.label,
        url=config.page.url,
        selector=" >> ".join([*config.extraction.frame_selectors, config.extraction.selector]),
        session_id=session_id,
        record_events=config.output.record_events,
        delimiter=config.output.csv_delimiter,
    )
    try:
        event_logger.open()
    except EventLogError as exc:
        console.say(f"ERROR: {exc}")
        return 2

    if config.extraction.method == "http":
        from .http_extractor import HttpExtractor

        extractor = HttpExtractor(config)
    else:
        from .browser_manager import BrowserManager

        extractor = BrowserManager(config)

    machine = StateMachine(
        {t.id: TargetInfo(text=t.text, mode=t.mode) for t in config.targets},
        required_observations=config.confirmation.required_observations,
        unknown_policy=config.confirmation.unknown_policy,
        rebaseline_after_failures=config.confirmation.rebaseline_after_failures,
    )
    monitor = Monitor(
        config, extractor, TextDetector(config), machine, event_logger,
        StateStore(config.output.state_path, config.fingerprint()), console,
    )

    def on_signal(signum: int, _frame) -> None:
        if monitor.stop_requested:
            if signum == signal.SIGINT:
                raise KeyboardInterrupt
            return
        reason = "detenido por el usuario (Ctrl+C)" if signum == signal.SIGINT else \
            f"detenido por la señal {signal.Signals(signum).name}"
        monitor.request_stop(reason)
        _write_now("\nDeteniendo… se termina la comprobación en curso (pulsa Ctrl+C otra vez para forzar).\n")

    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if sig is not None:
            previous[sig] = signal.signal(sig, on_signal)
    try:
        return monitor.run()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def cmd_check(args: argparse.Namespace) -> int:
    config = _load(args.config)
    if config is None:
        return 2
    from .console import Console

    Console(config.tz, config.output.terminal).banner(config, "configuración válida (no se ha accedido a la página)")
    print(f"Archivo de estado: {config.output.state_path}")
    print("Siguiente paso: python main.py probe   (comprueba el selector en la página real)")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    config = _load(args.config)
    if config is None:
        return 2
    from .probe import run_probe

    return run_probe(config, sys.stdout, find_text=args.find, samples=args.samples, every=args.every,
                     use_http=not args.no_http, use_browser=not args.no_browser, headed=args.headed)


def cmd_login(args: argparse.Namespace) -> int:
    config = _load(args.config)
    if config is None:
        return 2
    from .browser_manager import BrowserStartError, interactive_login

    print(f"Se abrirá un navegador con el perfil {config.browser.user_data_dir or '(sin configurar)'}.")
    print("Inicia sesión en la web como lo harías normalmente. El programa no ve ni guarda tu contraseña.")
    try:
        interactive_login(config, lambda: input("Cuando hayas terminado, vuelve aquí y pulsa Enter… "))
    except BrowserStartError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except (KeyboardInterrupt, EOFError):
        print("\nCancelado.")
        return 130
    print("Perfil guardado. Ahora comprueba el acceso con: python main.py probe")
    return 0


def cmd_demo_server(args: argparse.Namespace) -> int:
    from .demo_server import serve

    return serve(args.host, args.port, args.periodo, args.con_errores)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description=f"{APP_NAME} v{__version__}: detecta cuándo aparecen, desaparecen o cambian textos en una página web.",
    )
    parser.add_argument("--config", "-c", default=str(DEFAULT_CONFIG),
                        help="archivo de configuración TOML (por defecto: config.toml)")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMANDO")

    sub.add_parser("run", help="inicia el monitor (Ctrl+C para detenerlo)").set_defaults(func=cmd_run)
    sub.add_parser("check", help="valida la configuración sin acceder a la página").set_defaults(func=cmd_check)

    p = sub.add_parser("probe", help="diagnostica la página: HTML estático o JavaScript, iframes, selector")
    p.add_argument("--find", metavar="TEXTO", help="lista los elementos que contienen TEXTO y selectores candidatos")
    p.add_argument("--samples", type=int, default=3, help="lecturas sin recargar para ver si el texto cambia solo")
    p.add_argument("--every", type=float, default=5.0, help="segundos entre esas lecturas")
    p.add_argument("--no-http", action="store_true", help="no probar requests + BeautifulSoup")
    p.add_argument("--no-browser", action="store_true", help="no probar con el navegador")
    p.add_argument("--headed", action="store_true", help="mostrar la ventana del navegador")
    p.set_defaults(func=cmd_probe)

    sub.add_parser("login", help="abre el navegador para iniciar sesión a mano (perfil persistente)"
                   ).set_defaults(func=cmd_login)

    d = sub.add_parser("demo-server", help="servidor local de demostración para probar el monitor")
    d.add_argument("--host", default="127.0.0.1")
    d.add_argument("--port", type=int, default=8765)
    d.add_argument("--periodo", type=float, default=30.0, help="segundos que dura cada estado (por defecto 30)")
    d.add_argument("--con-errores", action="store_true", help="añade una fase en la que el servidor responde HTTP 503")
    d.set_defaults(func=cmd_demo_server)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)
