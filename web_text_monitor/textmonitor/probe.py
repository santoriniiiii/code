"""Diagnóstico de viabilidad para una página concreta (`python main.py probe`).

Responde con datos reales de la página configurada:
  * ¿El elemento está en el HTML que entrega el servidor (basta requests)?
  * ¿Solo aparece tras ejecutar JavaScript (hace falta el navegador)?
  * ¿Está dentro de un iframe? ¿Cuántos elementos coinciden con el selector?
  * ¿Hay texto oculto por CSS? ¿El texto cambia sin recargar la página?
  * Con --find TEXTO: qué elementos contienen ese texto y qué selectores
    estables (id, data-testid, aria-label...) los identifican de forma única.

No guarda nada en el historial. Solo hace las peticiones necesarias.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, TextIO

from .config import AppConfig
from .models import ObservationKind, RawObservation, ReadStatus
from .text_detector import TextDetector, truncate

FIND_JS = r"""
(needle) => {
  const lower = needle.toLowerCase();
  const skip = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'HEAD', 'TITLE']);
  const results = [];
  const quote = (v) => '"' + v.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
  const count = (sel) => { try { return document.querySelectorAll(sel).length; } catch (e) { return -1; } };
  for (const e of document.querySelectorAll('body *')) {
    if (skip.has(e.tagName)) continue;
    if (!(e.textContent || '').toLowerCase().includes(lower)) continue;
    let inChild = false;
    for (const c of e.children) {
      if ((c.textContent || '').toLowerCase().includes(lower)) { inChild = true; break; }
    }
    if (inChild) continue;  // solo el elemento más interno que contiene el texto
    const tag = e.tagName.toLowerCase();
    const candidates = [];
    if (e.id) candidates.push({selector: '#' + CSS.escape(e.id), source: 'id'});
    for (const a of ['data-testid', 'data-test', 'data-qa', 'data-cy', 'name', 'aria-label', 'role', 'title']) {
      const v = e.getAttribute(a);
      if (v) candidates.push({selector: tag + '[' + a + '=' + quote(v) + ']', source: a});
    }
    const classes = [...e.classList].slice(0, 3);
    if (classes.length) candidates.push({selector: tag + classes.map((c) => '.' + CSS.escape(c)).join(''), source: 'clase'});
    let parent = e.parentElement;
    while (parent && !parent.id) parent = parent.parentElement;
    if (parent && parent !== e) candidates.push({selector: '#' + CSS.escape(parent.id) + ' ' + tag, source: 'id de un antecesor'});
    for (const c of candidates) c.count = count(c.selector);
    const style = getComputedStyle(e);
    const box = e.getBoundingClientRect();
    results.push({
      tag: tag,
      text: (e.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 120),
      visible: style.visibility === 'visible' && box.width > 0 && box.height > 0,
      candidates: candidates,
    });
    if (results.length >= 15) break;
  }
  return results;
}
"""

IFRAMES_JS = """
(els) => els.map((e) => ({id: e.id, name: e.getAttribute('name') || '', title: e.title || '', src: e.src || ''}))
"""


@dataclass
class ProbeReport:
    http_status: int | None = None
    http_error: str = ""
    http_found: bool | None = None
    http_state: str | None = None
    browser_status: int | None = None
    browser_error: str = ""
    browser_found: bool | None = None
    browser_state: str | None = None
    hidden_text_differs: bool = False
    final_url: str = ""
    selector_in_frames: list[str] = field(default_factory=list)
    changed_without_reload: bool | None = None
    changed_after_load: bool = False
    notes: list[str] = field(default_factory=list)


class Prober:
    def __init__(self, config: AppConfig, out: TextIO):
        self.config = config
        self.out = out
        self.detector = TextDetector(config)
        self.report = ProbeReport()

    def p(self, text: str = "") -> None:
        print(text, file=self.out, flush=True)

    def title(self, text: str) -> None:
        self.p()
        self.p(text)
        self.p("-" * len(text))

    def describe(self, obs: RawObservation, label: str) -> str | None:
        interp = self.detector.interpret(obs)
        if interp.kind is ObservationKind.VALID:
            snap = interp.snapshot
            found = snap.matches_text() or "ninguno"
            self.p(f"  {label}: estado {snap.state!r}; textos encontrados: {found}")
            return snap.state
        self.p(f"  {label}: {interp.kind.value} ({interp.reason})")
        return None

    # ------------------------------------------------------------------ HTTP
    def probe_http(self) -> None:
        import requests
        from bs4 import BeautifulSoup

        from .http_extractor import charset_from_headers

        self.title("1. Sin navegador: requests + BeautifulSoup (HTML tal como lo envía el servidor)")
        r = self.report
        url = self.config.page.url
        if not url.startswith(("http://", "https://")):
            self.p("  La URL no es http(s); se omite esta prueba.")
            return
        t0 = time.perf_counter()
        try:
            response = requests.get(url, timeout=self.config.http.timeout_s,
                                    headers={"User-Agent": self.config.http.user_agent or "web-text-monitor-probe"})
        except requests.RequestException as exc:
            r.http_error = str(exc).splitlines()[0][:300]
            self.p(f"  ERROR: {r.http_error}")
            return
        r.http_status = response.status_code
        self.p(f"  HTTP {response.status_code} en {(time.perf_counter() - t0) * 1000:.0f} ms; "
               f"Content-Type {response.headers.get('Content-Type')!r}; {len(response.content)} bytes")
        if response.url != url:
            self.p(f"  Redirigido a: {response.url}")
        if response.status_code >= 400:
            r.http_error = f"HTTP {response.status_code}"
            return
        soup = BeautifulSoup(response.content, "html.parser",
                             from_encoding=charset_from_headers(response.headers.get("Content-Type")))
        scripts = len(soup.find_all("script"))
        iframes = soup.find_all("iframe")
        for tag in soup(["script", "style", "noscript", "template"]):
            tag.decompose()
        self.p(f"  <script>: {scripts}; <iframe>: {len(iframes)}")
        try:
            elements = soup.select(self.config.extraction.selector)
        except Exception as exc:
            self.p(f"  El selector no es CSS válido para BeautifulSoup: {exc}")
            r.http_found = False
            return
        r.http_found = bool(elements)
        self.p(f"  Elementos que coinciden con {self.config.extraction.selector!r}: {len(elements)}")
        for i, element in enumerate(elements[:5], start=1):
            self.p(f"    {i}. {truncate(' '.join(element.get_text(' ').split()), 160)!r}")
        if elements:
            obs = RawObservation(ReadStatus.OK, started_utc=_now(), duration_ms=0, method="http",
                                 texts=tuple(e.get_text(" ") for e in elements))
            r.http_state = self.describe(obs, "Interpretación")

    # --------------------------------------------------------------- navegador
    def probe_browser(self, headed: bool, samples: int, every: float, find_text: str | None) -> None:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright

        from .browser_manager import READ_ELEMENTS_JS, friendly_launch_error

        self.title("2. Con navegador: Playwright + Chromium (después de ejecutar JavaScript)")
        r = self.report
        cfg = self.config
        b = cfg.browser
        options: dict[str, Any] = dict(headless=not headed and b.headless, handle_sigint=False,
                                       handle_sigterm=False, handle_sighup=False)
        if b.channel:
            options["channel"] = b.channel
        if b.executable_path:
            options["executable_path"] = str(b.executable_path)
        with sync_playwright() as p:
            try:
                if b.user_data_dir:
                    b.user_data_dir.mkdir(parents=True, exist_ok=True)
                    context = p.chromium.launch_persistent_context(str(b.user_data_dir), **options)
                    browser = None
                else:
                    browser = p.chromium.launch(**options)
                    context = browser.new_context()
            except PlaywrightError as exc:
                r.browser_error = friendly_launch_error(exc, b.channel, b.user_data_dir, b.executable_path)
                self.p(f"  ERROR: {r.browser_error}")
                return
            try:
                context.set_default_timeout(cfg.extraction.element_timeout_s * 1000)
                page = context.pages[0] if context.pages else context.new_page()
                t0 = time.perf_counter()
                try:
                    response = page.goto(cfg.page.url, wait_until=cfg.extraction.wait_until,
                                         timeout=cfg.extraction.page_load_timeout_s * 1000)
                except PlaywrightError as exc:
                    r.browser_error = str(exc).splitlines()[0][:300]
                    self.p(f"  ERROR al cargar: {r.browser_error}")
                    return
                r.browser_status = response.status if response else None
                r.final_url = page.url
                self.p(f"  HTTP {r.browser_status} en {(time.perf_counter() - t0) * 1000:.0f} ms; título {page.title()!r}")
                if page.url != cfg.page.url:
                    self.p(f"  URL final: {page.url}")

                scope: Any = page
                for frame_selector in cfg.extraction.frame_selectors:
                    scope = scope.frame_locator(frame_selector)
                locator = scope.locator(cfg.extraction.selector)
                try:
                    locator.first.wait_for(state="attached", timeout=cfg.extraction.element_timeout_s * 1000)
                    data = locator.evaluate_all(READ_ELEMENTS_JS)
                except PlaywrightTimeoutError:
                    data = []
                except PlaywrightError as exc:
                    self.p(f"  ERROR al buscar el elemento: {str(exc).splitlines()[0][:300]}")
                    data = []
                r.browser_found = bool(data)
                where = f" dentro de {' -> '.join(cfg.extraction.frame_selectors)}" if cfg.extraction.frame_selectors else ""
                self.p(f"  Elementos que coinciden con {cfg.extraction.selector!r}{where}: {len(data)}")
                for i, d in enumerate(data[:5], start=1):
                    self.p(f"    {i}. visible={d['visible']} texto visible={truncate(' '.join(d['innerText'].split()), 100)!r}")
                    if " ".join(d["textContent"].split()) != " ".join(d["innerText"].split()):
                        r.hidden_text_differs = True
                        self.p(f"       texto completo (incluye partes ocultas)={truncate(' '.join(d['textContent'].split()), 100)!r}")
                if data:
                    r.browser_state = self.describe(self._browser_obs(data), "Interpretación")
                    later = self._settle_check(locator, READ_ELEMENTS_JS, data)
                    if later:
                        data = later
                        r.browser_state = self.describe(self._browser_obs(data), "Interpretación 2 s después")
                self._frames(page)
                if samples > 1 and data:
                    self._samples(locator, samples, every, READ_ELEMENTS_JS)
                if find_text:
                    self._find(page, find_text)
            finally:
                try:
                    context.close()
                    if browser is not None:
                        browser.close()
                except PlaywrightError:
                    pass

    def _frames(self, page: Any) -> None:
        r = self.report
        frames = page.frames
        self.p(f"  Frames de la página: {len(frames)} (el primero es el documento principal)")
        if len(frames) > 1:
            iframes = page.locator("iframe").evaluate_all(IFRAMES_JS)
            for info in iframes:
                self.p(f"    <iframe> id={info['id']!r} name={info['name']!r} title={info['title']!r} src={truncate(info['src'], 90)!r}")
        for frame in frames[1:]:
            try:
                n = frame.locator(self.config.extraction.selector).count()
            except Exception:
                continue
            if n:
                r.selector_in_frames.append(frame.url)
                self.p(f"    El selector existe dentro del iframe {truncate(frame.url, 90)!r} ({n} coincidencias)")

    def _browser_obs(self, data: list[dict]) -> RawObservation:
        if self.config.extraction.text_source == "visible":
            texts = tuple(d["innerText"] if d["visible"] else "" for d in data)
        else:
            texts = tuple(d["textContent"] for d in data)
        return RawObservation(ReadStatus.OK, started_utc=_now(), duration_ms=0, method="browser", texts=texts)

    def _settle_check(self, locator: Any, js: str, first: list[dict]) -> list[dict] | None:
        """¿El texto cambia en los primeros segundos tras cargar (p. ej. un "Cargando…")?

        Devuelve la segunda lectura si es distinta de la primera; si no, None.
        """
        time.sleep(2.0)
        try:
            later = locator.evaluate_all(js)
        except Exception:
            return None
        before = [" ".join(d["innerText"].split()) for d in first]
        after = [" ".join(d["innerText"].split()) for d in later]
        if before == after:
            return None
        self.report.changed_after_load = True
        self.p(f"  El texto cambió en los 2 s siguientes a la carga: {truncate(' | '.join(before), 60)!r} -> "
               f"{truncate(' | '.join(after), 60)!r}")
        return later

    def _samples(self, locator: Any, samples: int, every: float, js: str) -> None:
        self.p(f"  Lecturas sin recargar ({samples}, cada {every:g} s) para ver si el texto cambia solo:")
        seen: list[str] = []
        for i in range(samples):
            if i:
                time.sleep(every)
            try:
                data = locator.evaluate_all(js)
                text = " | ".join(" ".join(d["innerText"].split()) for d in data)
            except Exception as exc:
                text = f"(error: {str(exc).splitlines()[0][:80]})"
            seen.append(text)
            self.p(f"    {i + 1}. {truncate(text, 120)!r}")
        self.report.changed_without_reload = len(set(seen)) > 1

    def _find(self, page: Any, needle: str) -> None:
        self.title(f"3. Elementos que contienen {needle!r} (sin distinguir mayúsculas)")
        total = 0
        for index, frame in enumerate(page.frames):
            try:
                found = frame.evaluate(FIND_JS, needle)
            except Exception as exc:
                self.p(f"  (no se pudo inspeccionar el frame {frame.url}: {str(exc).splitlines()[0][:80]})")
                continue
            if not found:
                continue
            place = "documento principal" if index == 0 else f"iframe {truncate(frame.url, 80)}"
            for item in found:
                total += 1
                self.p(f"  [{place}] <{item['tag']}> visible={item['visible']} texto={item['text']!r}")
                for c in item["candidates"]:
                    if c["count"] == 1:
                        verdict = "único"
                    elif c["count"] < 0:
                        verdict = "no válido"
                    else:
                        verdict = f"{c['count']} coincidencias"
                    warn = "  (las clases pueden cambiar entre versiones de la web)" if c["source"] == "clase" else ""
                    self.p(f"      selector candidato: {c['selector']}  -> {verdict}{warn}")
                if not item["candidates"]:
                    self.p("      sin atributos estables: busca un antecesor con id o atributo data-*")
        if not total:
            self.p("  No se encontró ningún elemento con ese texto (¿aparece más tarde, tras iniciar sesión o en otra página?).")
        else:
            self.p("  Comprueba el candidato en las herramientas de desarrollo del navegador antes de usarlo.")

    # -------------------------------------------------------------- resumen
    def conclusions(self) -> None:
        r = self.report
        self.title("Conclusión")
        lines: list[str] = []
        if r.http_status in (401, 403) or r.browser_status in (401, 403):
            lines.append("La página respondió 401/403: puede requerir sesión iniciada o rechazar clientes automatizados. "
                         "Usa method = \"browser\" con user_data_dir y `python main.py login`. Si el sitio bloquea la "
                         "automatización, no intentes eludirlo: consulta si ofrece una API o un permiso explícito.")
        if r.final_url and r.final_url.rstrip("/") != self.config.page.url.rstrip("/"):
            lines.append(f"El navegador terminó en otra URL ({r.final_url}). Si es una pantalla de inicio de sesión, "
                         "usa user_data_dir y `python main.py login`.")
        if r.browser_found and r.http_found is False:
            lines.append("El elemento solo existe después de ejecutar JavaScript (o está en un iframe): "
                         "hace falta method = \"browser\".")
        elif r.browser_found and r.http_found:
            if (r.http_state is not None and r.http_state == r.browser_state and not r.hidden_text_differs
                    and not r.changed_after_load):
                lines.append("El elemento y el texto están en el HTML estático y coinciden con lo que muestra el "
                             "navegador: method = \"http\" sería suficiente y más ligero (repite la prueba en "
                             "distintos estados para confirmarlo).")
            else:
                lines.append("El HTML estático y la página renderizada no dicen lo mismo (JavaScript o CSS cambian el "
                             "texto): usa method = \"browser\".")
        if r.hidden_text_differs:
            lines.append("Hay texto oculto por CSS dentro del elemento: con method = \"browser\" y "
                         "text_source = \"visible\" solo se considera lo que se ve.")
        if r.browser_found is False:
            if r.selector_in_frames:
                lines.append("El selector existe dentro de un iframe: añade el selector del <iframe> en "
                             "frame_selectors (ver la lista de iframes de arriba).")
            else:
                lines.append("El navegador no encontró el selector. Revísalo (prueba --find \"texto\"), comprueba si "
                             "hace falta iniciar sesión o si el contenido aparece más tarde (element_timeout_seconds).")
        if r.changed_after_load:
            lines.append("El texto cambia justo después de cargar (marcador de carga o datos que llegan por JavaScript). "
                         "Con reload_each_check = true usa settle_seconds (p. ej. 2) o, mejor, reload_each_check = false.")
        if r.changed_without_reload:
            lines.append("El texto cambió sin recargar la página: puedes usar reload_each_check = false para no "
                         "recargarla en cada comprobación.")
        elif r.changed_without_reload is False:
            lines.append("Durante las lecturas sin recargar el texto no cambió (no prueba que nunca cambie solo).")
        if not lines:
            lines.append("No hay datos suficientes para recomendar un método; revisa los errores de arriba.")
        for line in lines:
            self.p(f"  - {line}")


def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def run_probe(config: AppConfig, out: TextIO, *, find_text: str | None = None, samples: int = 3,
              every: float = 5.0, use_http: bool = True, use_browser: bool = True, headed: bool = False) -> int:
    prober = Prober(config, out)
    prober.p(f"Diagnóstico de {config.page.url}")
    prober.p(f"Selector: {config.extraction.selector!r}"
             + (f" dentro de {list(config.extraction.frame_selectors)}" if config.extraction.frame_selectors else ""))
    if use_http:
        prober.probe_http()
    if use_browser:
        try:
            prober.probe_browser(headed=headed, samples=samples, every=every, find_text=find_text)
        except ImportError:
            prober.p("  Playwright no está instalado: pip install -r requirements.txt")
    prober.conclusions()
    return 0
