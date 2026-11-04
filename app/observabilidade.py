"""Erros do servidor enviados ao Sentry, quando SENTRY_DSN está definido. Sem a variável, nada acontece.

Privacidade: não envia IP, cookies, cabeçalhos nem o corpo das requisições (assim senha e CPF nunca saem do servidor)."""
import logging

from app.config import settings

log = logging.getLogger("brasilplus.sentry")


def iniciar() -> bool:
    if not settings.sentry_dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        log.warning("SENTRY_DSN definido, mas o pacote sentry-sdk não está instalado")
        return False
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        send_default_pii=False,        # sem IP, usuário, cookies
        max_request_body_size="never",  # nunca manda o corpo das requisições (senha, CPF)
        traces_sample_rate=0.0,        # só erros, sem performance
        environment="producao" if settings.expor_docs is False else "desenvolvimento",
    )
    return True
