"""Carga completa do robô: tarefas que mudam pouco são puladas enquanto a última coleta valer."""
import json
from datetime import date, datetime, timedelta

import pytest

from app.db import SessionLocal, criar_tabelas
from app.models import Coleta
from scripts import coleta_ci


@pytest.fixture
def banco():
    criar_tabelas()
    with SessionLocal() as db:
        db.query(Coleta).delete()
        db.commit()
    yield
    with SessionLocal() as db:
        db.query(Coleta).delete()
        db.commit()


def _coleta(fonte, tarefa, dias_atras, status="ok", **params):
    with SessionLocal() as db:
        db.add(Coleta(fonte=fonte, tarefa=tarefa, parametros={k: str(v) for k, v in params.items()}, status=status,
                      inicio=datetime.now() - timedelta(days=dias_atras, minutes=5), fim=datetime.now() - timedelta(days=dias_atras)))
        db.commit()


def test_pula_tributos_das_cidades_coletados_no_mes(banco):
    cmd = ["siconfi-tributos", "ano=2025", "esferas=M"]
    assert coleta_ci.ja_coletada(cmd) is None  # nunca rodou
    _coleta("siconfi", "tributos_entes", 3, status="parcial", ano=2025, bimestre=6, esferas="M")
    assert "vale por 30" in coleta_ci.ja_coletada(cmd)
    assert coleta_ci.ja_coletada(["siconfi-tributos", "ano=2025", "esferas=E"]) is None  # estados rodam sempre
    assert coleta_ci.ja_coletada(["siconfi-tributos", "ano=2024", "esferas=M"]) is None  # outro ano


def test_coleta_velha_ou_com_erro_nao_conta(banco):
    cmd = ["siconfi-tributos", "ano=2025", "esferas=M"]
    _coleta("siconfi", "tributos_entes", 40, ano=2025, esferas="M")
    _coleta("siconfi", "tributos_entes", 1, status="erro", ano=2025, esferas="M")
    assert coleta_ci.ja_coletada(cmd) is None


def test_despesas_por_funcao_anos_fechados(banco):
    hoje = date.today().year
    _coleta("siconfi", "despesas_funcao", 100, ano=hoje - 3, bimestre=6, esferas="U,E,C")
    _coleta("siconfi", "despesas_funcao", 100, ano=hoje - 1, bimestre=6, esferas="U,E,C")
    assert "vale por 365" in coleta_ci.ja_coletada(["siconfi-despesas-funcao", f"ano={hoje - 3}"])
    assert coleta_ci.ja_coletada(["siconfi-despesas-funcao", f"ano={hoje - 1}"]) is None  # último ano fechado: revisto todo mês
    assert coleta_ci.ja_coletada(["siconfi-despesas-funcao", f"ano={hoje}", "bimestre=4"]) is None  # ano atual sempre roda
    assert coleta_ci.ja_coletada(["bcb-series"]) is None  # sem regra


@pytest.mark.parametrize("dias,saida", [(1, 1), (10, 0), (None, 0)])
def test_midia_atrasada(tmp_path, dias, saida):
    if dias is not None:
        (tmp_path / "indice.json").write_text(json.dumps({"gerado_em": (date.today() - timedelta(days=dias)).isoformat()}))
    with pytest.raises(SystemExit) as e:
        coleta_ci.midia_atrasada(str(tmp_path))
    assert e.value.code == saida
