"""Proteções da API pública: limite de requisições por IP e cabeçalhos de segurança."""
import time
from collections import OrderedDict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import settings

CSP_SITE = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'")


class Protecao(BaseHTTPMiddleware):
    def __init__(self, app, por_minuto: int | None = None):
        super().__init__(app)
        self.por_minuto = settings.limite_req_por_minuto if por_minuto is None else por_minuto
        self.baldes: OrderedDict[str, list[float]] = OrderedDict()

    def _permitir(self, ip: str) -> bool:
        if self.por_minuto <= 0:
            return True
        agora = time.monotonic()
        fichas, ultimo = self.baldes.pop(ip, [float(self.por_minuto), agora])
        fichas = min(self.por_minuto, fichas + (agora - ultimo) * self.por_minuto / 60)
        ok = fichas >= 1
        self.baldes[ip] = [fichas - 1 if ok else fichas, agora]
        while len(self.baldes) > 50_000:  # memória limitada
            self.baldes.popitem(last=False)
        return ok

    async def dispatch(self, request, call_next):
        ip = request.client.host if request.client else "?"
        if request.url.path not in ("/saude",) and not self._permitir(ip):
            return JSONResponse({"detail": "Muitas requisições. Tente de novo em instantes."}, status_code=429,
                                headers={"Retry-After": "30"})
        resp = await call_next(request)
        h = resp.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if request.url.path == "/":
            h["Content-Security-Policy"] = CSP_SITE
            h["X-Frame-Options"] = "DENY"
        return resp
