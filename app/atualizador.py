"""Atualização automática do programa instalado (Windows). Consulta a última versão publicada no GitHub, baixa o instalador,
CONFERE o SHA-256 publicado junto e só então o roda em modo silencioso. Sem conferência, não instala.
Configuração (config.env): ATUALIZAR_AUTO=0 desliga a instalação sozinha (só avisa); ATUALIZAR_TOKEN = chave do GitHub só de LEITURA,
necessária se o repositório for privado; ATUALIZAR_REPO = dono/repositório (padrão abaixo)."""
from __future__ import annotations

import hashlib
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import httpx

from app.versao import VERSAO

log = logging.getLogger("brasilplus.atualizador")
REPO_PADRAO = "felponesx/politica"
INSTALADOR = "BRASILMais-Setup.exe"
LIMITE_BYTES = 600_000_000


def tupla(v: str) -> tuple[int, ...]:
    n = [int(x) for x in re.findall(r"\d+", v or "")][:3]
    return tuple(n + [0] * (3 - len(n)))


def e_mais_nova(atual: str, tag: str) -> bool:
    return tupla(tag) > tupla(atual)


def _cab(token: str, tipo: str = "application/vnd.github+json") -> dict:
    h = {"Accept": tipo, "User-Agent": "BRASILMais-atualizador", "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def consultar(repo: str, token: str = "", cliente: httpx.Client | None = None) -> dict | None:
    """Última versão publicada: {tag, url, sha256_url, sha256}. None se não há instalador nela."""
    c = cliente or httpx.Client(timeout=30, follow_redirects=True)
    r = c.get(f"https://api.github.com/repos/{repo}/releases/latest", headers=_cab(token))
    if r.status_code == 404:
        return None
    r.raise_for_status()
    rel = r.json()
    ativos = {a.get("name"): a for a in rel.get("assets", [])}
    a = ativos.get(INSTALADOR)
    if not a:
        return None
    digest = str(a.get("digest") or "")
    sha = digest.split(":", 1)[1] if digest.startswith("sha256:") else ""
    return {"tag": rel.get("tag_name", ""), "url": a["url"], "sha256": sha.lower(),
            "sha256_url": (ativos.get(INSTALADOR + ".sha256") or {}).get("url", ""), "tamanho": int(a.get("size") or 0)}


def _sha_publicado(info: dict, token: str, cliente: httpx.Client) -> str:
    if info.get("sha256"):
        return info["sha256"]
    if info.get("sha256_url"):
        r = cliente.get(info["sha256_url"], headers=_cab(token, "application/octet-stream"))
        r.raise_for_status()
        m = re.search(r"\b[0-9a-fA-F]{64}\b", r.text)
        return m.group(0).lower() if m else ""
    return ""


def baixar(info: dict, pasta: Path, token: str = "", cliente: httpx.Client | None = None) -> Path:
    """Baixa para `pasta` e confere o SHA-256. Levanta ValueError se não houver hash publicado ou se não bater."""
    c = cliente or httpx.Client(timeout=120, follow_redirects=True)
    esperado = _sha_publicado(info, token, c)
    if not esperado:
        raise ValueError("a versão nova não traz o SHA-256 para conferir; não instalo")
    pasta.mkdir(parents=True, exist_ok=True)
    destino, parcial = pasta / INSTALADOR, pasta / (INSTALADOR + ".part")
    h, total = hashlib.sha256(), 0
    with c.stream("GET", info["url"], headers=_cab(token, "application/octet-stream")) as r:
        r.raise_for_status()
        with parcial.open("wb") as f:
            for bloco in r.iter_bytes(1 << 20):
                total += len(bloco)
                if total > LIMITE_BYTES:
                    raise ValueError("arquivo grande demais")
                h.update(bloco)
                f.write(bloco)
    if h.hexdigest() != esperado:
        parcial.unlink(missing_ok=True)
        raise ValueError("o SHA-256 do instalador não confere; descartei o arquivo")
    parcial.replace(destino)
    return destino


def aplicar(instalador: Path) -> None:
    """Roda o instalador em silêncio e solta o processo (o instalador fecha o programa, troca os arquivos e abre de novo)."""
    flags = (0x00000008 | 0x00000200) if sys.platform == "win32" else 0   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([str(instalador), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=flags, close_fds=True)


def verificar(sair=None, avisar=None, base: Path | None = None) -> str:
    """Um ciclo: consulta, baixa, confere e instala (ou só avisa). Devolve uma frase com o que aconteceu. Nunca levanta erro."""
    if not (getattr(sys, "frozen", False) and sys.platform == "win32"):
        return "atualização automática só vale no programa instalado (Windows)"
    repo, token = os.environ.get("ATUALIZAR_REPO", REPO_PADRAO), os.environ.get("ATUALIZAR_TOKEN", "")
    auto = os.environ.get("ATUALIZAR_AUTO", "1") != "0"
    try:
        info = consultar(repo, token)
        if not info or not e_mais_nova(VERSAO, info["tag"]):
            return f"já está na versão mais nova ({VERSAO})"
        if not auto:
            if avisar:
                avisar(f"Versão nova {info['tag']} disponível. Ligue ATUALIZAR_AUTO=1 para instalar sozinho.")
            return f"versão {info['tag']} disponível (instalação automática desligada)"
        pasta = Path(os.environ.get("BRASILPLUS_BASE", ".")) / "atualizacao"
        arquivo = baixar(info, pasta, token)
        if avisar:
            avisar(f"Atualizando para {info['tag']}. O BRASIL+ vai fechar e abrir sozinho.")
        aplicar(arquivo)
        if sair:
            sair()
        return f"instalando {info['tag']}"
    except Exception as e:   # rede fora, repositório sem acesso, hash errado: o programa segue como está
        log.warning("atualização não feita: %s", e)
        return f"não consegui atualizar: {type(e).__name__}"
