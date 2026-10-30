import ipaddress
import logging
import random
import socket
import time
from functools import lru_cache
from urllib.parse import urlsplit

import httpx

from app.config import settings

log = logging.getLogger("brasilplus.http")



@lru_cache(maxsize=1024)
def _enderecos(host: str) -> tuple:
    try:
        return tuple({a[4][0] for a in socket.getaddrinfo(host, None)})
    except OSError:
        return ()  # não resolveu aqui (ex.: DNS só pelo proxy): deixa o httpx tentar; o que importa é nunca chegar a um IP interno


def url_segura(url) -> None:
    """Barra endereço que não seja http(s) público: localhost, rede privada, link-local (metadados de nuvem) etc. Vale para cada
    requisição de saída, inclusive os redirecionamentos, para que uma URL passada em POST /coletas não alcance a rede interna (SSRF)."""
    u = urlsplit(str(url))
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError(f"URL não permitida: {u.scheme or '?'}")
    host = u.hostname.lower()
    if host in ("localhost", "metadata.google.internal") or host.endswith((".local", ".internal")):
        raise ValueError("endereço interno não permitido")
    for ip in (host,) if _eh_ip(host) else _enderecos(host):
        a = ipaddress.ip_address(ip)
        if a.is_private or a.is_loopback or a.is_link_local or a.is_reserved or a.is_multicast or a.is_unspecified:
            raise ValueError("endereço interno não permitido")


def _eh_ip(h: str) -> bool:
    try:
        ipaddress.ip_address(h)
        return True
    except ValueError:
        return False


def _barrar_interno(request: httpx.Request):
    if settings.bloquear_rede_interna:
        url_segura(request.url)


_cliente = httpx.Client(
    event_hooks={"request": [_barrar_interno]},
    timeout=settings.http_timeout,
    follow_redirects=True,
    headers={"Accept": "application/json", "User-Agent": "BRASIL+ coletor (transparencia)"},
)


def get(url: str, params: dict | None = None, headers: dict | None = None, timeout: float | None = None) -> httpx.Response:
    """GET com retentativa exponencial para 429/5xx e falhas de rede."""
    espera = 2.0
    for tentativa in range(1, settings.http_retries + 1):
        try:
            r = _cliente.get(url, params=params, headers=headers, **({"timeout": timeout} if timeout else {}))
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
            pausa = espera * (0.5 + random.random())  # variação aleatória: vários coletores não voltam todos no mesmo instante
            depois = (resp.headers.get("Retry-After", "") if resp is not None else "").strip()
            if depois.isdigit():
                pausa = min(max(pausa, float(depois)), 120.0)  # respeita o pedido da fonte (HTTP 429/503)
            log.warning("Falha em %s (%s). Tentando de novo em %.0fs", url.split("?")[0], type(e).__name__, pausa)
            time.sleep(pausa)
            espera *= 2
    raise RuntimeError("inalcançável")


def get_json(url: str, params: dict | None = None, headers: dict | None = None):
    r = get(url, params=params, headers=headers)
    if not r.content:
        return None
    return r.json()


def baixar(url: str, destino: str):
    """Download em streaming (arquivos grandes do TSE)."""
    # Accept */*: o portal gov.br (Plone) trata "Accept: application/json" como chamada à API dele e responde 401
    with _cliente.stream("GET", url, timeout=httpx.Timeout(60.0, read=300.0), headers={"Accept": "*/*"}) as r:
        r.raise_for_status()
        with open(destino, "wb") as f:
            for bloco in r.iter_bytes(1 << 20):
                f.write(bloco)
    return destino


def get_json_uma_vez(url: str, params: dict | None = None, timeout: float = 20.0):
    """GET sem retentativa (para consultas em lote que têm alternativa, como o cadastro de CNPJ)."""
    r = _cliente.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json() if r.content else None
