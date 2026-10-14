"""Lectura con un navegador real: Playwright + Chromium.

Necesario cuando el texto lo genera JavaScript, cambia sin recargar, está
dentro de un iframe, depende del CSS (visible u oculto) o la página exige
una sesión iniciada en el navegador.

Comportamiento comprobado en la prueba de concepto (poc/):
  * innerText de un elemento con display:none devuelve su texto igualmente,
    por eso se comprueba la visibilidad antes de usarlo.
  * Tras una navegación fallida, reutilizar la misma pestaña puede dar un
    error espurio ("interrupted by another navigation"), por eso tras un
    error se descarta la pestaña y se abre otra.
  * Con las opciones por defecto, Ctrl+C cierra el navegador a mitad de una
    lectura; con handle_sigint=False la lectura en curso termina bien y el
    programa puede cerrar ordenadamente.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable

from .config import AppConfig
from .models import RawObservation, ReadStatus

log = logging.getLogger(__name__)

# Lee en una sola llamada (una "foto" coherente) el texto y la visibilidad de
# todos los elementos que coinciden. Criterio de visibilidad similar al de
# Playwright: caja con tamaño > 0 y visibility:visible (display:contents no
# tiene caja propia y se considera visible).
READ_ELEMENTS_JS = """
(elements) => elements.map((e) => {
  const style = window.getComputedStyle(e);
  const box = e.getBoundingClientRect();
  const visible = style.display === 'contents' ||
    (style.visibility === 'visible' && box.width > 0 && box.height > 0);
  const inner = typeof e.innerText === 'string' ? e.innerText : (e.textContent || '');
  return { visible: visible, innerText: inner, textContent: e.textContent || '' };
})
"""


class BrowserStartError(Exception):
    """No se pudo iniciar el navegador (mensaje pensado para el usuario)."""


def friendly_launch_error(exc: BaseException, channel: str, user_data_dir: Any,
                          executable_path: Any = None) -> str:
    text = str(exc)
    if "executable doesn't exist" in text.lower():
        if executable_path:
            return f"No existe el navegador indicado en [browser] executable_path: {executable_path}"
        return ("No se encontró el navegador de Playwright. Con el entorno virtual activo ejecuta:\n"
                "    python -m playwright install chromium")
    if channel and ("is not found" in text or "not found at" in text):
        return (f"No se encontró el navegador del canal {channel!r} (p. ej. Google Chrome instalado). "
                "Instálalo o deja channel = \"\" para usar el Chromium de Playwright.")
    if user_data_dir and ("ProcessSingleton" in text or "SingletonLock" in text or "profile" in text.lower()):
        return (f"El perfil {user_data_dir} parece estar en uso por otro navegador o monitor. "
                "Cierra la otra ventana o usa otro user_data_dir.")
    first_line = text.strip().splitlines()[0] if text.strip() else type(exc).__name__
    return f"No se pudo iniciar el navegador: {first_line[:300]}"


def _short(exc: BaseException) -> str:
    text = str(exc).strip()
    first = text.splitlines()[0] if text else type(exc).__name__
    return first[:300]


class BrowserManager:
    def __init__(self, config: AppConfig):
        self._cfg = config
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._context_closed = False
        self._needs_navigation = True
        engine = config.browser.channel or "chromium"
        source = "texto visible" if config.extraction.text_source == "visible" else "texto completo del DOM"
        self.method = f"navegador Playwright ({engine}, {source})"

    # ----------------------------------------------------------- ciclo de vida
    def start(self) -> None:
        """Inicia el navegador. Lanza BrowserStartError si no es posible."""
        self._ensure_context()

    def close(self) -> None:
        self._reset()

    def _ensure_context(self) -> None:
        if self._context is not None and self._healthy():
            return
        self._reset()
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise BrowserStartError(
                "Playwright no está instalado. Con el entorno virtual activo ejecuta: "
                "pip install -r requirements.txt"
            ) from None
        b = self._cfg.browser
        options: dict[str, Any] = dict(
            headless=b.headless,
            # El programa gestiona Ctrl+C por su cuenta (ver poc/poc_ctrl_c.py).
            handle_sigint=False,
            handle_sigterm=False,
            handle_sighup=False,
        )
        if b.channel:
            options["channel"] = b.channel
        if b.executable_path:
            options["executable_path"] = str(b.executable_path)
        try:
            self._pw = sync_playwright().start()
            chromium = self._pw.chromium
            if b.user_data_dir:
                b.user_data_dir.mkdir(parents=True, exist_ok=True)
                os.chmod(b.user_data_dir, 0o700)  # el perfil contiene cookies de sesión
                self._context = chromium.launch_persistent_context(str(b.user_data_dir), **options)
            else:
                self._browser = chromium.launch(**options)
                self._context = self._browser.new_context()
            self._context_closed = False
            self._context.on("close", self._on_context_close)
            self._context.set_default_timeout(self._cfg.extraction.element_timeout_s * 1000)
            self._context.set_default_navigation_timeout(self._cfg.extraction.page_load_timeout_s * 1000)
            log.info("Navegador iniciado (%s, headless=%s)", b.channel or "chromium", b.headless)
        except (PlaywrightError, OSError) as exc:
            log.debug("Fallo al iniciar el navegador", exc_info=True)
            self._reset()
            raise BrowserStartError(friendly_launch_error(exc, b.channel, b.user_data_dir, b.executable_path)) from exc

    def _on_context_close(self, *_: Any) -> None:
        self._context_closed = True

    def _healthy(self) -> bool:
        if self._context is None or self._context_closed:
            return False
        if self._browser is not None and not self._browser.is_connected():
            return False
        return True

    def _ensure_page(self) -> Any:
        if self._page is None or self._page.is_closed():
            existing = [p for p in self._context.pages if not p.is_closed()]
            self._page = existing[0] if existing else self._context.new_page()
            self._needs_navigation = True
        return self._page

    def _discard_page(self) -> None:
        page, self._page = self._page, None
        self._needs_navigation = True
        if page is not None:
            try:
                page.close()
            except Exception:
                pass

    def _reset(self) -> None:
        """Cierra todo sin lanzar excepciones (también si el navegador ya murió)."""
        self._discard_page()
        for name, closer in (("context", "close"), ("browser", "close"), ("pw", "stop")):
            obj = getattr(self, f"_{name}")
            setattr(self, f"_{name}", None)
            if obj is None:
                continue
            try:
                getattr(obj, closer)()
            except Exception as exc:
                log.debug("Ignorado al cerrar %s: %s", name, exc)
        self._context_closed = False

    # --------------------------------------------------------------- lectura
    def _navigate(self, page: Any) -> Any:
        url = self._cfg.page.url
        wait_until = self._cfg.extraction.wait_until
        if page.url == url:
            # reload() revalida la página en la caché del navegador
            return page.reload(wait_until=wait_until)
        return page.goto(url, wait_until=wait_until)

    def _locator(self, page: Any) -> Any:
        scope = page
        for frame_selector in self._cfg.extraction.frame_selectors:
            scope = scope.frame_locator(frame_selector)
        return scope.locator(self._cfg.extraction.selector)

    def observe(self) -> RawObservation:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        started = datetime.now(timezone.utc)
        t0 = time.perf_counter()
        ex = self._cfg.extraction

        def result(status: ReadStatus, **kwargs: Any) -> RawObservation:
            return RawObservation(status=status, started_utc=started,
                                  duration_ms=(time.perf_counter() - t0) * 1000, method=self.method, **kwargs)

        http_status: int | None = None
        navigated = False
        try:
            self._ensure_context()
            page = self._ensure_page()
            if self._needs_navigation or ex.reload_each_check:
                navigated = True
                response = self._navigate(page)
                self._needs_navigation = False
                http_status = response.status if response is not None else None
                if http_status is not None and http_status >= 400:
                    self._needs_navigation = True
                    return result(ReadStatus.ERROR, detail=f"el servidor respondió HTTP {http_status}",
                                  http_status=http_status, final_url=page.url)
            locator = self._locator(page)
            try:
                locator.first.wait_for(state="attached", timeout=ex.element_timeout_s * 1000)
            except PlaywrightTimeoutError:
                self._needs_navigation = True  # la próxima vez se vuelve a cargar la URL configurada
                return result(
                    ReadStatus.ELEMENT_NOT_FOUND,
                    detail=f"{ex.selector!r} no apareció en {ex.element_timeout_s:g} s (URL actual: {page.url})",
                    http_status=http_status, final_url=page.url,
                )
            if navigated and ex.settle_s > 0:
                # Margen para que el JavaScript de la página sustituya marcadores como "Cargando…".
                page.wait_for_timeout(ex.settle_s * 1000)
            data = locator.evaluate_all(READ_ELEMENTS_JS)
            if not data:
                self._needs_navigation = True
                return result(ReadStatus.ELEMENT_NOT_FOUND, detail=f"{ex.selector!r} desapareció durante la lectura",
                              http_status=http_status, final_url=page.url)
            if ex.text_source == "visible":
                texts = tuple(d["innerText"] if d["visible"] else "" for d in data)
            else:
                texts = tuple(d["textContent"] for d in data)
            return result(ReadStatus.OK, texts=texts, http_status=http_status, final_url=page.url)
        except BrowserStartError as exc:
            self._reset()
            return result(ReadStatus.ERROR, detail=str(exc))
        except PlaywrightTimeoutError as exc:
            self._discard_page()
            return result(ReadStatus.ERROR, detail=f"tiempo de espera agotado: {_short(exc)}", http_status=http_status)
        except PlaywrightError as exc:
            if self._healthy():
                self._discard_page()
            else:
                log.warning("El navegador se cerró o se desconectó; se reiniciará en la próxima comprobación")
                self._reset()
            return result(ReadStatus.ERROR, detail=_short(exc), http_status=http_status)
        except Exception as exc:  # fallo inesperado: se registra completo y se reinicia todo
            log.exception("Fallo inesperado leyendo la página")
            self._reset()
            return result(ReadStatus.ERROR, detail=f"fallo inesperado: {type(exc).__name__}: {_short(exc)}")


def interactive_login(config: AppConfig, wait_for_user: Callable[[], Any] = input) -> None:
    """Abre una ventana visible con el perfil persistente para iniciar sesión a mano.

    El programa no ve ni guarda la contraseña: el usuario la escribe en el
    sitio web y el navegador guarda la cookie de sesión en user_data_dir.
    """
    b = config.browser
    if not b.user_data_dir:
        raise BrowserStartError("Configura [browser] user_data_dir para guardar la sesión iniciada.")
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise BrowserStartError("Playwright no está instalado: pip install -r requirements.txt") from None
    options: dict[str, Any] = dict(headless=False, handle_sigint=False, handle_sigterm=False, handle_sighup=False)
    if b.channel:
        options["channel"] = b.channel
    if b.executable_path:
        options["executable_path"] = str(b.executable_path)
    b.user_data_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(b.user_data_dir, 0o700)
    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(str(b.user_data_dir), **options)
        except PlaywrightError as exc:
            raise BrowserStartError(friendly_launch_error(exc, b.channel, b.user_data_dir, b.executable_path)) from exc
        try:
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto(config.page.url, timeout=config.extraction.page_load_timeout_s * 1000)
            except PlaywrightError as exc:
                print(f"Aviso: no se pudo abrir la URL automáticamente ({_short(exc)}). Navega a mano.")
            wait_for_user()
        finally:
            try:
                context.close()
            except PlaywrightError:
                pass
