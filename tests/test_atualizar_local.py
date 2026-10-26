"""Atualizador do PC: só avança com testes e subida bons; volta e avisa quando algo reprova."""
import subprocess

import pytest

from scripts import atualizar_local as al


def _git(pasta, *a):
    return subprocess.run(["git", *a], cwd=pasta, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repos(tmp_path):
    origem, trabalho, pc = tmp_path / "origem.git", tmp_path / "trabalho", tmp_path / "pc"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origem)], check=True)
    subprocess.run(["git", "clone", "-q", str(origem), str(trabalho)], check=True, capture_output=True)
    for r in (trabalho,):
        _git(r, "config", "user.email", "t@t")
        _git(r, "config", "user.name", "t")
    (trabalho / "a.txt").write_text("v1")
    _git(trabalho, "add", "-A")
    _git(trabalho, "commit", "-qm", "v1")
    _git(trabalho, "push", "-q", "origin", "HEAD:main")
    subprocess.run(["git", "clone", "-q", "-b", "main", str(origem), str(pc)], check=True, capture_output=True)
    return trabalho, pc


def _enviar(trabalho, texto):
    (trabalho / "a.txt").write_text(texto)
    _git(trabalho, "add", "-A")
    _git(trabalho, "commit", "-qm", f"muda para {texto}")
    _git(trabalho, "push", "-q", "origin", "HEAD:main")


class Falso:
    """Roda git de verdade e finge o Docker: `testes` e `sobe` dizem se passam."""
    def __init__(self, testes=True, sobe=True):
        self.testes, self.sobe, self.chamadas = testes, sobe, []

    def __call__(self, cmd, pasta, timeout=0):
        if cmd[0] == "git":
            r = subprocess.run(cmd, cwd=pasta, capture_output=True, text=True)
            return r.returncode, (r.stdout + r.stderr).strip()
        self.chamadas.append(cmd[-1] if "pytest" not in cmd else "pytest")
        if "pytest" in cmd:
            return (0 if self.testes else 1), "1 failed" if not self.testes else "ok"
        return 0, ""


def _atualizador(pc, falso, avisos, saudavel=lambda: True):
    return al.Atualizador(pc, "main", rodar=falso, avisar=avisos.append, saudavel=saudavel)


def test_em_dia_nao_faz_nada(repos):
    _, pc = repos
    falso, avisos = Falso(), []
    assert _atualizador(pc, falso, avisos).conferir() == "em dia" and not falso.chamadas and not avisos


def test_atualiza_quando_testes_e_sistema_passam(repos):
    trabalho, pc = repos
    _enviar(trabalho, "v2")
    falso, avisos = Falso(), []
    assert _atualizador(pc, falso, avisos).conferir() == "atualizado"
    assert (pc / "a.txt").read_text() == "v2" and "pytest" in falso.chamadas
    assert len(avisos) == 1 and "atualizado" in avisos[0]
    assert (pc / ".atualizador" / "ultimo_bom").read_text().strip() == _git(pc, "rev-parse", "HEAD")


def test_testes_reprovados_voltam_a_versao_boa_e_nao_repetem(repos):
    trabalho, pc = repos
    bom = _git(pc, "rev-parse", "HEAD")
    _enviar(trabalho, "v2-quebrada")
    falso, avisos = Falso(testes=False), []
    at = _atualizador(pc, falso, avisos)
    assert at.conferir() == "reprovado"
    assert _git(pc, "rev-parse", "HEAD") == bom and (pc / "a.txt").read_text() == "v1"
    assert "testes reprovaram" in avisos[0] and "Voltei" in avisos[0]
    n = len(falso.chamadas)
    assert at.conferir() == "reprovado" and len(falso.chamadas) == n and len(avisos) == 1  # a mesma versão não é testada de novo
    _enviar(trabalho, "v3-boa")  # chegou uma versão nova: tenta
    falso.testes = True
    assert at.conferir() == "atualizado" and (pc / "a.txt").read_text() == "v3-boa"


def test_sistema_que_nao_sobe_volta(repos):
    trabalho, pc = repos
    _enviar(trabalho, "v2")
    avisos = []
    assert _atualizador(pc, Falso(), avisos, saudavel=lambda: False).conferir() == "reprovado"
    assert (pc / "a.txt").read_text() == "v1" and "não subiu" in avisos[0]


def test_recusa_quando_ha_arquivo_alterado_a_mao(repos):
    trabalho, pc = repos
    _enviar(trabalho, "v2")
    (pc / "a.txt").write_text("editado a mão")
    falso, avisos = Falso(), []
    assert _atualizador(pc, falso, avisos).conferir() == "recusado"
    assert (pc / "a.txt").read_text() == "editado a mão" and not falso.chamadas and "alterados à mão" in avisos[0]


def test_ramo_padrao_e_o_que_esta_aberto_na_pasta(repos):
    _, pc = repos
    assert al.Atualizador(pc, rodar=Falso(), avisar=[].append).ramo == "main"
