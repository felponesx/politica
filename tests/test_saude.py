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


# ---------- DATASUS TabNet (resposta real, resumida: 3 estados + total) ----------
TABNET_LEITOS = '''<html><H1>CNES - Leitos de internação - Brasil</H1><PRE>
"Unidade da Federação";"Cirúrgicos";"Clínicos";"Obstétrico";"Total"
"11 Rondônia";1565;2244;665;5429
"12 Acre";413;629;218;1607
"17 Tocantins";1322;1186;-;3682
"Total";126918;177406;49622;460549
&
</PRE>'''


def test_tabnet_tabela_e_por_uf():
    from app.collectors import datasus
    linhas = datasus.tabela(TABNET_LEITOS)
    assert linhas[0] == ["Unidade da Federação", "Cirúrgicos", "Clínicos", "Obstétrico", "Total"] and len(linhas) == 5
    ufs, total = datasus.por_uf(linhas)
    assert ufs["AC"] == {"Cirúrgicos": 413, "Clínicos": 629, "Obstétrico": 218, "Total": 1607}
    assert ufs["TO"]["Obstétrico"] == 0 and total["Total"] == 460549 and set(ufs) == {"RO", "AC", "TO"}
    assert datasus.numero("1.234") == 1234 and datasus.numero("12,56") == 12.56 and datasus.numero("-") == 0
    assert datasus.competencia("ltbr2609.dbf") == "2026-09"


def _ufs27(valor):
    from app.utils import UF_POR_CODIGO_IBGE
    return "\n".join(f'"{c} {u}";{valor(i)}' for i, (c, u) in enumerate(UF_POR_CODIGO_IBGE.items()))


def test_mortalidade_infantil_usa_so_ano_final_e_guarda_o_preliminar(monkeypatch):
    from app.collectors import datasus
    anos_ob = {2022: 100, 2023: 90, 2024: 80, 2025: 70}
    anos_nas = {2022: 10000, 2023: 9500, 2024: 9000, 2025: 9100}

    def tab(valores):
        cab = '"Unidade da Federação";' + ";".join(f'"{a}"' for a in valores) + ';"Total"'
        corpo = _ufs27(lambda i: ";".join(str(v) for v in valores.values()) + ";0")
        return f"<PRE>\n{cab}\n{corpo}\n\"Total\";" + ";".join(str(v * 27) for v in valores.values()) + ";0\n&"

    monkeypatch.setattr(datasus, "arquivos_disponiveis", lambda caminho: [f"{'infuf' if 'inf10' in caminho else 'nvuf'}{a % 100}.dbf" for a in (2022, 2023, 2024, 2025)])
    monkeypatch.setattr(datasus, "ANO_INICIAL", 2022)
    monkeypatch.setattr(datasus, "_post", lambda caminho, dados: tab(anos_ob if "inf10" in caminho else anos_nas))
    r = datasus.ler_mortalidade_infantil(ano_final=2026)
    assert r["BR"]["ultimo_ano"] == "2024" and sorted(r["BR"]["serie"]) == ["2022", "2023", "2024"]  # 2025 é preliminar: fica fora da série
    assert r["SP"]["serie"]["2024"]["taxa"] == pytest.approx(80 / 9000 * 1000, abs=0.01) and r["BR"]["preliminar"]["2025"]["obitos"] == 70 * 27


def test_leitura_com_estados_faltando_nao_grava(monkeypatch):
    from app.collectors import datasus
    monkeypatch.setattr(datasus, "_post", lambda caminho, dados: TABNET_LEITOS)
    with pytest.raises(RuntimeError, match="27"):
        datasus.ler_medicos("pfbr2609.dbf")


def test_painel_com_leitos_uti_medicos_e_mortalidade():
    criar_tabelas()
    cliente = TestClient(app)
    with SessionLocal() as db:
        _base(db)
        db.query(Registro).filter(Registro.fonte == "datasus").delete()
        uti = {"UTI adulto II": 60, "UTI neonatal II": 20, "Unidade de cuidados intermed adulto": 30, "Total": 110}
        db.add(Registro(fonte="datasus", tipo="leitos_uf", chave="AC", dados={
            "competencia_internacao": "2026-09", "competencia_uti": "2026-09", "internacao": {"Clínicos": 1000, "Total": 1500}, "internacao_sus": {"Clínicos": 900, "Total": 1200},
            "uti": uti, "uti_sus": {"UTI adulto II": 40, "UTI neonatal II": 10, "Total": 70}}))
        db.add(Registro(fonte="datasus", tipo="medicos_uf", chave="AC", dados={"competencia": "2026-09", "total": 1610, "por_cbo": {"Médico Clínico": 669}}))
        db.add(Registro(fonte="datasus", tipo="mortalidade_infantil_uf", chave="AC", dados={"ultimo_ano": "2024", "serie": {
            "2023": {"obitos": 250, "nascidos": 14000, "taxa": 17.86}, "2024": {"obitos": 245, "nascidos": 14239, "taxa": 17.21}}}))
        db.add(Registro(fonte="datasus", tipo="mortalidade_infantil_uf", chave="BR", dados={"ultimo_ano": "2024", "serie": {"2024": {"obitos": 30020, "nascidos": 2389325, "taxa": 12.56}},
                                                                                           "preliminar": {"2025": {"obitos": 29904, "nascidos": 2456688, "taxa": 12.17}}}))
        db.commit()
    try:
        from app.utils import _MEMO
        _MEMO.clear()
        d = cliente.get("/saude/painel").json()
        ac = d["estados"]["AC"]
        assert ac["leitos"] == 1500 and ac["leitos_sus"] == 1200 and ac["pct_leitos_sus"] == 80.0 and ac["leitos_por_mil"] == pytest.approx(1500 / 500_000 * 1000, abs=0.01)
        assert ac["uti"] == 80 and ac["uti_sus"] == 50 and ac["leitos_complementares"] == 110  # UTI não soma unidade intermediária
        assert ac["uti_por_100mil"] == pytest.approx(80 / 500_000 * 100000, abs=0.01)
        assert ac["medicos"] == 1610 and ac["medicos_por_mil"] == pytest.approx(1610 / 500_000 * 1000, abs=0.01)
        assert ac["tmi"] == 17.21 and ac["tmi_ano"] == "2024" and ac["tmi_serie"] == {"2023": 17.86, "2024": 17.21}
        b = d["brasil"]
        assert b["tmi"] == 12.56 and b["tmi_preliminar"]["2025"]["taxa"] == 12.17 and b["leitos"] == 1500 and b["medicos"] == 1610
        assert d["competencias"] == {"leitos": "2026-09", "uti": "2026-09", "medicos": "2026-09"}
    finally:
        with SessionLocal() as db:
            db.query(Registro).filter(Registro.fonte.in_(["saude", "datasus"])).delete()
            db.commit()
