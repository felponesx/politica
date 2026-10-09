import logging
import time

import httpx

from app.config import settings

log = logging.getLogger("brasilplus.http")

_cliente = httpx.Client(
    timeout=settings.http_timeout,
    follow_redirects=True,
    headers={"Accept": "application/json", "User-Agent": "BRASIL+ coletor (transparencia)"},
)


def get(url: str, params: dict | None = None, headers: dict | None = None) -> httpx.Response:
    """GET com retentativa exponencial para 429/5xx e falhas de rede."""
    espera = 2.0
    for tentativa in range(1, settings.http_retries + 1):
        try:
            r = _cliente.get(url, params=params, headers=headers)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
            r.raise_for_status()
            return r
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            resp = getattr(e, "response", None)
            if resp is not None and resp.status_code < 500 and resp.status_code != 429:
                raise
            if tentativa == settings.http_retries:
                raise
            log.warning("Falha em %s (%s). Tentando de novo em %.0fs", url, e, espera)
            time.sleep(espera)
            espera *= 2
    raise RuntimeError("inalcançável")


def get_json(url: str, params: dict | None = None, headers: dict | None = None):
    r = get(url, params=params, headers=headers)
    if not r.content:
        return None
    return r.json()


def baixar(url: str, destino: str):
    """Download em streaming (arquivos grandes do TSE)."""
    with _cliente.stream("GET", url, timeout=None) as r:
        r.raise_for_status()
        with open(destino, "wb") as f:
            for bloco in r.iter_bytes(1 << 20):
                f.write(bloco)
    return destino
