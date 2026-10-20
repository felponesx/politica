"""Padronização de textos e siglas (app/limpeza.py), com exemplos reais encontrados na cópia dos dados."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

from app.collectors.ibge import INDICADORES  # noqa: E402
from app.db import SessionLocal, criar_tabelas  # noqa: E402
from app.limpeza import limpar, partido, texto  # noqa: E402
from app.models import Registro  # noqa: E402
from app.utils import upsert  # noqa: E402


def test_textos_reais():
    assert texto("AquisiÃ§Ã£o de mesas para refeitÃ³rio, destinadas Ã\xa0 Creche ") == \
        "Aquisição de mesas para refeitório, destinadas à Creche"
    assert texto("J A SOBRAL &amp; CIA LTDA - BONOCO") == "J A SOBRAL & CIA LTDA - BONOCO"
    assert texto("EDINA WANDERLEY ") == "EDINA WANDERLEY"
    assert texto("Altera  disposições  sobre  servidores") == "Altera disposições sobre servidores"
    assert texto("linha 1  \n  linha 2") == "linha 1\nlinha 2"
    # texto certo não muda
    for ok in ("SÃO PAULO", "São Paulo & Cia", "R&D", "Ação nº 1"):
        assert texto(ok) == ok
    assert texto("-") is None and texto("-", vazio_none=False) == "-"


def test_siglas_de_partido():
    assert {partido(x) for x in ("PC do B", "PC DO B", "PCDOB", "PCdoB")} == {"PCdoB"}
    assert partido("SD") == "SOLIDARIEDADE" and partido("PATRI") == "PATRIOTA" and partido("PT do B") == "PT do B"
    # nomes antigos e coligações ficam como eram
    assert [partido(x) for x in ("PMDB", "PFL", "Sem partido", "PT/PCdoB")] == ["PMDB", "PFL", "Sem partido", "PT/PCdoB"]
    d = limpar({"partido": "PC DO B", "nome": " ROSSO &amp; ROSSO ", "itens": [{"sg_partido": "SD", "x": 1}]})
    assert d == {"partido": "PCdoB", "nome": "ROSSO & ROSSO", "itens": [{"sg_partido": "SOLIDARIEDADE", "x": 1}]}


def test_upsert_grava_limpo():
    criar_tabelas()
    with SessionLocal() as db:
        db.query(Registro).filter(Registro.fonte == "teste-limpeza").delete()
        r = upsert(db, Registro, {"fonte": "teste-limpeza", "tipo": "t", "chave": "1"},
                   {"titulo": "  Contratação  de  obra ", "dados": {"fornecedor": "D &amp; B LTDA", "partido": "PATRI"}})
        db.commit()
        assert r.titulo == "Contratação de obra" and r.dados == {"fornecedor": "D & B LTDA", "partido": "PATRIOTA"}
        db.delete(r)
        db.commit()


def test_ibge_pib_per_capita_usa_variavel_em_reais():
    assert INDICADORES["pib_per_capita"][:2] == (5938, 593)
