"""Publicações próprias do BRASIL+ (escritas pelo administrador): regras de texto, link de vídeo, foto e slug.

Vídeo: só YouTube ou Vimeo; o link é convertido para o endereço de incorporação (nada de código HTML vindo do administrador).
Foto: JPEG, PNG ou WebP até 3 MB, conferidos pelos bytes do arquivo (não pelo nome).
Texto: sem HTML; linhas com '|' viram tabela (dados próprios) e linhas em branco separam parágrafos.
"""
from __future__ import annotations

import base64
import re
import unicodedata
from urllib.parse import parse_qs, urlparse

from app.models import Publicacao

CATEGORIAS = ("noticia", "dados", "destaque")
TIPOS_IMAGEM = {"image/jpeg", "image/png", "image/webp"}
LIMITE_FOTO = 3 * 1024 * 1024
LIMITE_CORPO = 20000


class ErroPublicacao(Exception):
    def __init__(self, mensagem: str, status: int = 400):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status


def slugify(texto: str) -> str:
    base = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base[:150] or "publicacao"


def link_video(url: str | None) -> str | None:
    """Aceita o link comum do YouTube ou do Vimeo e devolve o endereço de incorporação. Qualquer outro site é recusado."""
    if not url or not url.strip():
        return None
    u = urlparse(url.strip())
    if u.scheme != "https":
        raise ErroPublicacao("O link do vídeo precisa começar com https://")
    host = (u.hostname or "").lower()
    if host in ("youtube.com", "www.youtube.com", "m.youtube.com"):
        vid = parse_qs(u.query).get("v", [""])[0]
        if u.path.startswith("/embed/"):
            vid = u.path.split("/")[2] if len(u.path.split("/")) > 2 else ""
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid or ""):
            return f"https://www.youtube-nocookie.com/embed/{vid}"
    elif host in ("youtu.be", "www.youtu.be"):
        vid = u.path.strip("/").split("/")[0]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
            return f"https://www.youtube-nocookie.com/embed/{vid}"
    elif host in ("vimeo.com", "www.vimeo.com"):
        m = re.fullmatch(r"/(\d{6,12})", u.path.rstrip("/"))
        if m:
            return f"https://player.vimeo.com/video/{m.group(1)}"
    raise ErroPublicacao("Use um link do YouTube ou do Vimeo.")


def link_imagem(url: str | None) -> str | None:
    if not url or not url.strip():
        return None
    u = urlparse(url.strip())
    if u.scheme != "https" or not u.hostname:
        raise ErroPublicacao("O link da imagem precisa começar com https://")
    return url.strip()[:500]


def tipo_da_foto(dados: bytes) -> str | None:
    """Confere o tipo pelos primeiros bytes do arquivo."""
    if dados[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if dados[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
        return "image/webp"
    return None


def decodifica_foto(dados_base64: str) -> tuple[bytes, str]:
    try:
        bruto = base64.b64decode(dados_base64.split(",", 1)[-1], validate=True)
    except (ValueError, TypeError):
        raise ErroPublicacao("Arquivo de foto inválido.")
    if len(bruto) == 0 or len(bruto) > LIMITE_FOTO:
        raise ErroPublicacao("A foto precisa ter até 3 MB.")
    tipo = tipo_da_foto(bruto)
    if tipo is None:
        raise ErroPublicacao("Envie uma foto em JPEG, PNG ou WebP.")
    return bruto, tipo


def valida_campos(titulo: str, resumo: str | None, corpo: str, categoria: str, fonte: str | None,
                  video: str | None, capa_url: str | None) -> dict:
    titulo = " ".join((titulo or "").split())
    if not (4 <= len(titulo) <= 200):
        raise ErroPublicacao("O título precisa ter entre 4 e 200 caracteres.")
    corpo = (corpo or "").replace("\r\n", "\n").strip()
    if not corpo:
        raise ErroPublicacao("Escreva o texto da publicação.")
    if len(corpo) > LIMITE_CORPO:
        raise ErroPublicacao("O texto passou de 20 mil caracteres.")
    if categoria not in CATEGORIAS:
        raise ErroPublicacao("Categoria inválida.")
    return {
        "titulo": titulo,
        "resumo": " ".join((resumo or "").split())[:400] or None,
        "corpo": corpo,
        "categoria": categoria,
        "fonte": " ".join((fonte or "").split())[:300] or None,
        "video_url": link_video(video),
        "capa_url": link_imagem(capa_url),
    }


def capa_de(p: Publicacao) -> str | None:
    if p.capa_midia_id:
        return f"/midia/{p.capa_midia_id}"
    return p.capa_url


def resumo_de(p: Publicacao) -> dict:
    return {"slug": p.slug, "titulo": p.titulo, "resumo": p.resumo, "categoria": p.categoria,
            "capa": capa_de(p), "publicada_em": p.publicada_em.isoformat() if p.publicada_em else None}


def completo_de(p: Publicacao) -> dict:
    return {**resumo_de(p), "corpo": p.corpo, "video": p.video_url, "fonte": p.fonte,
            "publicada": p.publicada, "atualizada_em": p.atualizada_em.isoformat() if p.atualizada_em else None}
