"""Saúde: UBS e Mais Médicos (Ministério da Saúde) por município e painel por estado, com linhas no formato real da API de Dados Abertos."""
import pytest
from fastapi.testclient import TestClient

from app.collectors import saude as coletor
from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import Municipio, Registro

# linhas reais (resumidas) de GET /assistencia-a-saude/unidade-basicas-de-saude (22/10/2026)
UBS = [
    {"ibge": "260290", "bairro": "PONTE DOS CARVALHOS", "logradouro": "RUA DO CEMITERIO", "cnes": "0000302", "uf": "26", "nome": "USF SANTO ESTEVAO"},
    {"ibge": "260290", "bairro": "CENTRO", "logradouro": "RUA A", "cnes": "0000310", "uf": "26", "nome": "USF CENTRO"},
    {"ibge": "260290", "bairro": "CENTRO", "logradouro": "RUA A", "cnes": "0000310", "uf": "26", "nome": "USF CENTRO (repetida)"},   # mesmo CNES: conta uma vez
    {"ibge": "120040", "bairro": "X", "logradouro": "Y", "cnes": "0000500", "uf": "12", "nome": "UBS RIO BRANCO"},
    {"ibge": "", "cnes": "0000999", "nome": "sem município"},
]
# linhas reais (resumidas) de GET /atencao-primaria/pmmb-consolidado (09/10/2026)
MAIS_MEDICOS = [
    {"nivel": "MUNICIPAL", "uf": "RO", "co_ibge": 110143, "municipio_dsei": "NOVA UNIAO", "total_vagas_ativas": 4.0, "total_ocupadas": 4.0,
     "total_desocupadas": 0.0, "em_processo_ocupacao": 0.0, "dt_referencia": "2026-10-09"},
    {"nivel": "MUNICIPAL", "uf": "AC", "co_ibge": 120040, "municipio_dsei": "RIO BRANCO", "total_vagas_ativas": 75.0, "total_ocupadas": 70.0,
     "total_desocupadas": 4.0, "em_processo_ocupacao": 1.0, "dt_referencia": "2026-10-09"},
    {"nivel": "DSEI", "uf": "AL", "co_ibge": 1, "municipio_dsei": "ALAGOAS E SERGIPE", "total_vagas_ativas": 14.0, "total_ocupadas": 13.0, "dt_referencia": "2026-10-09"},
    {"nivel": "ESTADUAL", "uf": "AC", "co_ibge": 12, "municipio_dsei": "ACRE", "total_vagas_ativas": 2.0, "total_ocupadas": 2.0, "dt_referencia": "2026-10-09"},
]


def test_contar_ubs_por_municipio_sem_repetir_cnes():
    assert coletor.contar_ubs(UBS) == {"260290": 2, "120040": 1}


def test_mais_medicos_separa_municipio_de_estadual_e_indigena():
    por_mun, resto = coletor.resumir_mais_medicos(MAIS_MEDICOS)
    assert por_mun == {"110143": {"vagas": 4, "ocupadas": 4, "desocupadas": 0, "em_processo": 0},
                       "120040": {"vagas": 75, "ocupadas": 70, "desocupadas": 4, "em_processo": 1}}
    assert resto["dsei"] == {"vagas": 14, "ocupadas": 13} and resto["estadual"] == {"vagas": 2, "ocupadas": 2} and resto["data_referencia"] == "2026-10-09"


def test_leitura_cortada_nao_vira_o_dado_do_pais(monkeypatch):
    criar_tabelas()
    monkeypatch.setattr(coletor, "_paginas", lambda caminho, chave: iter(UBS if chave == "ubs" else MAIS_MEDICOS))
    with pytest.raises(RuntimeError, match="incompleta"):
        coletor.coletar_ubs()
    with pytest.raises(RuntimeError, match="incompleta"):
        coletor.coletar_mais_medicos()


def test_paginas_segue_o_offset_ate_a_pagina_curta(monkeypatch):
    chamadas = []

    def get_json(url, params=None, headers=None):
        chamadas.append(params["offset"])
        n = 1000 if params["offset"] < 2000 else 7
        return {"ubs": [{"cnes": str(params["offset"] + i)} for i in range(n)]}
    monkeypatch.setattr(coletor.http, "get_json", get_json)
    assert len(list(coletor._paginas("assistencia-a-saude/unidade-basicas-de-saude", "ubs"))) == 2007
    assert chamadas == [0, 1000, 2000]


def _base(db):
    db.query(Registro).filter(Registro.fonte == "saude").delete()
    for cod, nome, uf, pop in (("1200401", "Rio Branco", "AC", 400_000), ("1200013", "Acrelândia", "AC", 100_000), ("2700300", "Arapiraca", "AL", 1_000_000)):
        if not db.query(Municipio).filter_by(codigo_ibge=cod).first():
            db.add(Municipio(codigo_ibge=cod, nome=nome, uf=uf, populacao=pop))
    for cod, q in {"120040": 10, "270030": 30}.items():
        db.add(Registro(fonte="saude", tipo="ubs_municipio", chave=cod, uf={"12": "AC", "27": "AL"}[cod[:2]], valor=float(q), dados={"ubs": q}))
    db.add(Registro(fonte="saude", tipo="mais_medicos_municipio", chave="120040", uf="AC", valor=70.0,
                    dados={"vagas": 75, "ocupadas": 70, "desocupadas": 4, "em_processo": 1, "data_referencia": "2026-10-09"}))
    db.add(Registro(fonte="saude", tipo="mais_medicos_resumo", chave="BR", dados={"estadual": {"vagas": 2, "ocupadas": 2}, "dsei": {"vagas": 14, "ocupadas": 13},
                                                                                "data_referencia": "2026-10-09"}))
    db.commit()


def test_painel_e_rotas():
    criar_tabelas()
    cliente = TestClient(app)
    with SessionLocal() as db:
        _base(db)
    try:
        from app.utils import _MEMO
        _MEMO.clear()
        d = cliente.get("/saude/painel").json()
        ac, al = d["estados"]["AC"], d["estados"]["AL"]
        assert ac["ubs"] == 10 and ac["ubs_por_100mil"] == pytest.approx(10 / 500_000 * 100000, abs=0.01) and ac["municipios_sem_ubs"] == 1  # Acrelândia sem UBS
        assert ac["mm_vagas"] == 75 and ac["mm_ocupadas"] == 70 and ac["mm_pct_ocupadas"] == pytest.approx(93.3, abs=0.1)
        assert al["ubs"] == 30 and "mm_ocupadas" in al and al["mm_ocupadas"] == 0
        assert d["brasil"]["ubs"] >= 40 and d["brasil"]["mm_data"] == "2026-10-09" and d["brasil"]["mm_fora_de_municipio"]["dsei"]["ocupadas"] == 13
        assert d["notas"] and d["fontes"]
        m = cliente.get("/saude/municipios", params={"uf": "AC"}).json()["itens"]
        assert [x["nome"] for x in m] == ["Rio Branco", "Acrelândia"]
        assert m[0]["ubs"] == 10 and m[0]["mm_ocupadas"] == 70 and m[1]["ubs"] == 0 and m[1]["mm_vagas"] is None
        assert cliente.get("/saude/municipios", params={"uf": "ZZ"}).status_code == 422
        assert cliente.get("/saude").json() == {"status": "ok"}  # a rota de saúde do sistema continua igual
    finally:
        with SessionLocal() as db:
            db.query(Registro).filter(Registro.fonte == "saude").delete()
            db.commit()
