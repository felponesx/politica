"""Entrega automática da cópia: commit só com mudança, só a pasta de dados, e envio para um remoto (aqui, um repositório local)."""
import subprocess
from pathlib import Path

import pytest

from app import entrega


def _g(pasta, *a):
    return subprocess.run(["git", "-C", str(pasta), *a], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repos(tmp_path):
    remoto, clone = tmp_path / "remoto.git", tmp_path / "clone"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remoto)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(clone)], check=True)
    (clone / "LEIA.md").write_text("x", encoding="utf-8")
    _g(clone, "add", "LEIA.md")
    _g(clone, *entrega.AUTOR, "commit", "-q", "-m", "inicial")
    _g(clone, "remote", "add", "origin", str(remoto))
    _g(clone, "push", "-q", "-u", "origin", "main")
    return clone, remoto


def _gerador(texto):
    def gerar(destino: Path):
        (destino / "p").mkdir(parents=True, exist_ok=True)
        (destino / "p" / "eventos.json").write_text(texto, encoding="utf-8")
    return gerar


def test_envia_quando_ha_mudanca_e_nao_repete_sem_mudanca(repos):
    clone, remoto = repos
    assert entrega.entregar(clone, gerar=_gerador('{"v": 1}')) == "enviada"
    assert "site/dados/p/eventos.json" in _g(remoto, "ls-tree", "-r", "--name-only", "main")
    assert entrega.entregar(clone, gerar=_gerador('{"v": 1}')) == "sem mudanças nos dados"
    assert entrega.entregar(clone, gerar=_gerador('{"v": 2}')) == "enviada"


def test_so_commita_a_pasta_de_dados(repos):
    clone, _ = repos
    (clone / "trabalho.txt").write_text("não é para entrar", encoding="utf-8")
    _g(clone, "add", "trabalho.txt")          # alterado à mão e já no índice: não pode ir junto
    entrega.entregar(clone, gerar=_gerador('{"v": 3}'), enviar=False)
    arquivos = _g(clone, "show", "--name-only", "--format=", "HEAD").split()
    assert arquivos == ["site/dados/p/eventos.json"]


def test_falha_de_geracao_nao_derruba(repos):
    clone, _ = repos

    def quebra(destino):
        raise RuntimeError("banco fora")
    assert entrega.entregar(clone, gerar=quebra).startswith("cópia não gerada")


def test_desligada_sem_variavel(monkeypatch):
    monkeypatch.delenv("ENTREGA_GIT_PASTA", raising=False)
    assert entrega.entregar_se_configurado().startswith("desligada")
