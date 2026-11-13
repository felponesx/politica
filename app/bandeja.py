"""Ícone perto do relógio (Windows): abrir o painel e sair. Sem a biblioteca (ou fora do Windows), o programa roda sem ícone."""
from __future__ import annotations

import logging
import webbrowser

log = logging.getLogger("brasilplus.bandeja")
_icone = None


def _imagem():
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((2, 2, 62, 62), radius=14, fill=(47, 111, 237, 255))
    d.rectangle((28, 14, 36, 50), fill="white")
    d.rectangle((14, 28, 50, 36), fill="white")
    return im


def notificar(texto: str) -> None:
    try:
        if _icone is not None:
            _icone.notify(texto, "BRASIL+")
    except Exception:
        log.debug("aviso não mostrado", exc_info=True)


def rodar(porta: int, versao: str, ao_sair) -> bool:
    """Mostra o ícone e BLOQUEIA até a pessoa escolher Sair. Devolve False se não deu para mostrar (sem ícone)."""
    global _icone
    try:
        import pystray
        menu = pystray.Menu(
            pystray.MenuItem("Abrir o painel", lambda *_: webbrowser.open(f"http://127.0.0.1:{porta}/painel"), default=True),
            pystray.MenuItem(f"Versão {versao}", None, enabled=False),
            pystray.MenuItem("Sair", lambda icone, *_: (ao_sair(), icone.stop())))
        _icone = pystray.Icon("BRASILMais", _imagem(), f"BRASIL+ {versao}", menu)
    except Exception:
        log.warning("sem ícone perto do relógio", exc_info=True)
        return False
    _icone.run()
    return True
