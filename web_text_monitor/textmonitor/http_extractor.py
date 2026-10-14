"""Lectura sin navegador: requests + BeautifulSoup.

Sirve cuando el texto ya viene en el HTML que entrega el servidor. No ejecuta
JavaScript, no entra en iframes y no evalúa el CSS (un elemento oculto con
CSS se lee igual). Es más ligero y rápido que un navegador.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from email.message import Message

import requests
from bs4 import BeautifulSoup

from . import __version__
from .config import AppConfig
from .models import RawObservation, ReadStatus

log = logging.getLogger(__name__)

# Elementos cuyo contenido nunca es texto visible.
_NON_TEXT_TAGS = ["script", "style", "noscript", "template"]


def charset_from_headers(content_type: str | None) -> str | None:
    """Charset declarado en Content-Type, o None si el servidor no lo declara.

    No se usa `response.encoding` de requests porque, sin charset, supone
    ISO-8859-1 para text/html (comprobado en la prueba de concepto: convierte
    "…" en "â\\x80¦"). Sin charset, BeautifulSoup lo detecta desde <meta charset>.
    """
    if not content_type:
        return None
    msg = Message()
    msg["content-type"] = content_type
    return msg.get_param("charset")  # type: ignore[return-value]


class HttpExtractor:
    def __init__(self, config: AppConfig, session: requests.Session | None = None):
        self._url = config.page.url
        self._selector = config.extraction.selector
        self._timeout = config.http.timeout_s
        self._session = session or requests.Session()
        self._session.headers["User-Agent"] = config.http.user_agent or f"web-text-monitor/{__version__}"
        self._session.headers["Cache-Control"] = "no-cache"
        self.method = "http (requests+BeautifulSoup, texto del HTML)"

    def start(self) -> None:
        """No necesita preparación."""

    def observe(self) -> RawObservation:
        started = datetime.now(timezone.utc)
        t0 = time.perf_counter()

        def result(status: ReadStatus, **kwargs) -> RawObservation:
            return RawObservation(
                status=status, started_utc=started, duration_ms=(time.perf_counter() - t0) * 1000,
                method=self.method, **kwargs,
            )

        try:
            response = self._session.get(self._url, timeout=self._timeout)
        except requests.Timeout:
            return result(ReadStatus.ERROR, detail=f"tiempo de espera agotado ({self._timeout:g} s)")
        except requests.ConnectionError as exc:
            return result(ReadStatus.ERROR, detail=f"no se pudo conectar: {_short(exc)}")
        except requests.RequestException as exc:
            return result(ReadStatus.ERROR, detail=f"error HTTP: {_short(exc)}")

        if response.status_code >= 400:
            return result(
                ReadStatus.ERROR, detail=f"el servidor respondió HTTP {response.status_code}",
                http_status=response.status_code, final_url=response.url,
            )
        try:
            soup = BeautifulSoup(
                response.content, "html.parser",
                from_encoding=charset_from_headers(response.headers.get("Content-Type")),
            )
            for tag in soup(_NON_TEXT_TAGS):
                tag.decompose()
            elements = soup.select(self._selector)
        except Exception as exc:  # HTML imposible de analizar o selector no válido
            log.debug("Fallo al analizar el HTML", exc_info=True)
            return result(ReadStatus.ERROR, detail=f"no se pudo analizar el HTML: {_short(exc)}",
                          http_status=response.status_code, final_url=response.url)

        if not elements:
            return result(
                ReadStatus.ELEMENT_NOT_FOUND,
                detail=f"{self._selector!r} no coincide con ningún elemento del HTML recibido (URL final: {response.url})",
                http_status=response.status_code, final_url=response.url,
            )
        texts = tuple(element.get_text(" ") for element in elements)
        return result(ReadStatus.OK, texts=texts, http_status=response.status_code, final_url=response.url)

    def close(self) -> None:
        self._session.close()


def _short(exc: BaseException) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return text[:300]
