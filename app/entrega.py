"""Entrega automática da cópia dos dados ao GitHub (programa instalado).

Liga quando a variável ENTREGA_GIT_PASTA aponta para um clone do repositório (no PC: a pasta do projeto).
A cada rodada: gera a cópia em <pasta>/site/dados (o banco do próprio programa), e só se houver mudança faz commit
apenas dessa pasta e envia pelo branch atual. Sem mudança: não faz commit. Falha de rede ou de Git não derruba o programa:
vira uma frase no log e tenta de novo na próxima rodada."""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger("brasilplus.entrega")
AUTOR = ("-c", "user.name=BRASIL+ automático", "-c", "user.email=brasilplus@users.noreply.github.com")
MENSAGEM = "Atualiza a copia dos dados (automatico) [skip ci]"


def _git(pasta: Path, *args: str, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(pasta), *args], capture_output=True, text=True, timeout=timeout)


def entregar(pasta: Path, gerar=None, enviar: bool = True) -> str:
    """Uma rodada. `gerar(destino)` grava a cópia (por padrão, a exportação do programa). Devolve o que aconteceu."""
    if gerar is None:
        from scripts.exportar_snapshot import main as exportar
        gerar = lambda destino: exportar([str(destino)])   # noqa: E731
    destino = pasta / "site" / "dados"
    try:
        gerar(destino)
    except Exception as e:   # a exportação falhar não pode derrubar o programa
        log.warning("entrega: a cópia não foi gerada (%s)", type(e).__name__)
        return f"cópia não gerada: {type(e).__name__}"
    add = _git(pasta, "add", "--", str(destino))
    if add.returncode:
        return "git add falhou"
    mudou = _git(pasta, "diff", "--cached", "--name-only", "--", str(destino)).stdout.strip()
    if not mudou:
        return "sem mudanças nos dados"
    commit = _git(pasta, *AUTOR, "commit", "-q", "-m", MENSAGEM, "--", str(destino))
    if commit.returncode:
        return "commit falhou"
    if not enviar:
        return "commit feito (sem envio)"
    branch = _git(pasta, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    push = _git(pasta, "push", "-q", "origin", f"HEAD:{branch}", timeout=300)
    if push.returncode:
        log.warning("entrega: envio ao GitHub falhou; tenta de novo na próxima rodada")
        return "envio falhou (tenta de novo depois)"
    log.info("entrega: cópia dos dados enviada ao branch %s", branch)
    return "enviada"


def entregar_se_configurado() -> str:
    """Chamada pelo agendador: só faz algo se ENTREGA_GIT_PASTA estiver definida."""
    pasta = os.environ.get("ENTREGA_GIT_PASTA", "").strip()
    if not pasta:
        return "desligada (sem ENTREGA_GIT_PASTA)"
    return entregar(Path(pasta))
