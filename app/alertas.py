"""Avisos de falha das coletas (Telegram ou qualquer webhook). Sem configuração, só registra no log."""
import logging

import httpx

from app.config import settings

log = logging.getLogger("brasilplus.alertas")


def enviar(texto: str) -> bool:
    log.warning("ALERTA: %s", texto)
    try:
        if settings.alerta_telegram_token and settings.alerta_telegram_chat:
            httpx.post(f"https://api.telegram.org/bot{settings.alerta_telegram_token}/sendMessage",
                       json={"chat_id": settings.alerta_telegram_chat, "text": texto}, timeout=15)
            return True
        if settings.alerta_webhook_url:
            httpx.post(settings.alerta_webhook_url, json={"texto": texto}, timeout=15)
            return True
    except Exception as e:  # alerta nunca derruba o agendador
        log.error("Não consegui enviar o alerta: %s", type(e).__name__)
    return False
