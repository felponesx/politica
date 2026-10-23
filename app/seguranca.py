"""Proteções da API pública: IP real do cliente (só com proxy confiável), limite do corpo, limite de requisições
compartilhado entre processos e cabeçalhos de segurança."""
import ipaddress
import logging
import time
from collections import OrderedDict

from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app import limites
from app.config import settings

log = logging.getLogger("brasilplus.seguranca")

CSP_SITE = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'; object-src 'none'")
METODOS = {"GET", "HEAD", "OPTIONS", "POST"}  # a API só lê; POST é das coletas (com token) e das rotas de IA
PESADAS = ("/busca", "/exportar", "/ia/", "/obras-gestao/lista")  # consultas caras: limite próprio, mais baixo
SEM_LIMITE = ("/saude", "/pronto")


# ---------- IP real do cliente ----------
def _redes(csv: str):
    out = []
    for x in (csv or "").split(","):
        x = x.strip()
        if not x:
            continue
        try:
            out.append(ipaddress.ip_network(x, strict=False))
        except ValueError:
            log.error("PROXIES_CONFIAVEIS tem um valor inválido: %r (ignorado)", x)
    return out


def _confiavel(ip: str, redes) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(a in r for r in redes)


def ip_cliente(request) -> str:
    """IP do cliente. X-Forwarded-For só vale quando a conexão vem de um proxy listado em PROXIES_CONFIAVEIS; nesse caso
    percorre a lista da direita para a esquerda e fica com o primeiro endereço que não é de proxy confiável (o que o nosso
    proxy viu de verdade). Valores falsos escritos pelo cliente ficam à esquerda e nunca são usados."""
    par = request.client.host if request.client else "?"
    redes = _redes(settings.proxies_confiaveis)
    if not redes or not _confiavel(par, redes):
        return par
    cadeia = [x.strip() for x in request.headers.get("x-forwarded-for", "").split(",") if x.strip()]
    for ip in reversed(cadeia):
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            return par  # lixo no cabeçalho: não confia em nada dele
        if not _confiavel(ip, redes):
            return ip
    return par


def _https(request) -> bool:
    if request.url.scheme == "https":
        return True
    par = request.client.host if request.client else ""
    return request.headers.get("x-forwarded-proto") == "https" and _confiavel(par, _redes(settings.proxies_confiaveis))


# ---------- corpo da requisição (limite no que realmente chega, com ou sem Content-Length) ----------
class LimiteCorpo:
    """ASGI puro: lê o corpo até o limite e devolve 413 se passar, mesmo sem Content-Length ou com valor mentiroso."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        limite = settings.corpo_max_bytes
        if scope["type"] != "http" or limite <= 0 or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        for k, v in scope["headers"]:
            if k == b"content-length":
                try:
                    if int(v) > limite:
                        return await self._recusar(scope, receive, send)
                except ValueError:
                    return await self._recusar(scope, receive, send, 400)
        mensagens, total = [], 0
        while True:
            m = await receive()
            if m["type"] == "http.disconnect":
                return
            mensagens.append(m)
            total += len(m.get("body", b""))
            if total > limite:
                return await self._recusar(scope, receive, send)
            if not m.get("more_body", False):
                break
        fila = iter(mensagens)

        async def replay():
            try:
                return next(fila)
            except StopIteration:
                return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def _recusar(scope, receive, send, status=413):
        msg = "Pedido grande demais." if status == 413 else "Pedido inválido."
        await JSONResponse({"detail": msg}, status_code=status, headers={"Connection": "close"})(scope, receive, send)


class Protecao(BaseHTTPMiddleware):
    def __init__(self, app, por_minuto: int | None = None):
        super().__init__(app)
        self.por_minuto = settings.limite_req_por_minuto if por_minuto is None else por_minuto
        self.baldes: OrderedDict[str, list[float]] = OrderedDict()

    def _balde_local(self, chave: str, limite: int) -> bool:
        """Reserva por processo: usada só quando o contador compartilhado está fora do ar (continua limitando, de forma menos exata)."""
        agora = time.monotonic()
        fichas, ultimo = self.baldes.pop(chave, [float(limite), agora])
        fichas = min(limite, fichas + (agora - ultimo) * limite / 60)
        ok = fichas >= 1
        self.baldes[chave] = [fichas - 1 if ok else fichas, agora]
        while len(self.baldes) > 50_000:
            self.baldes.popitem(last=False)
        return ok

    async def _checar(self, chave: str, limite: int):
        """(permitido, restante, segundos até reiniciar). Contador compartilhado; se falhar, balde local."""
        try:
            r = await run_in_threadpool(limites.consumir, chave, limite, 60)
            return r.ok, r.restante, r.reinicia_em
        except limites.LimiteIndisponivel:
            return self._balde_local(chave, limite), 0, 30

    async def dispatch(self, request, call_next):
        if request.method not in METODOS:
            return JSONResponse({"detail": "Método não permitido."}, status_code=405, headers={"Allow": "GET, HEAD, OPTIONS, POST"})
        caminho = request.url.path
        ip = ip_cliente(request)
        cab = {}
        if caminho not in SEM_LIMITE and not caminho.startswith("/midia/"):
            ok, resta, espera = True, None, 30
            if self.por_minuto > 0:
                ok, resta, espera = await self._checar(f"rl:{ip}", self.por_minuto)
                cab = {"X-RateLimit-Limit": str(self.por_minuto), "X-RateLimit-Remaining": str(resta)}
            if ok and settings.limite_pesado_por_minuto > 0 and caminho.startswith(PESADAS):
                ok, resta, espera = await self._checar(f"rp:{ip}", settings.limite_pesado_por_minuto)
                cab = {"X-RateLimit-Limit": str(settings.limite_pesado_por_minuto), "X-RateLimit-Remaining": str(resta)}
            if not ok:
                return JSONResponse({"detail": "Muitas requisições. Tente de novo em instantes."}, status_code=429,
                                    headers={"Retry-After": str(max(1, espera)), **cab, "X-RateLimit-Remaining": "0"})
        resp = await call_next(request)
        h = resp.headers
        for k, v in cab.items():
            h.setdefault(k, v)
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=(), usb=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if _https(request):
            h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.method == "POST":
            h["Cache-Control"] = "no-store"
        elif caminho.startswith("/midia/"):
            h.setdefault("Cache-Control", "public, max-age=3600")
        if caminho == "/":
            h["Content-Security-Policy"] = CSP_SITE
            h["X-Frame-Options"] = "DENY"
        return resp
