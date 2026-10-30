"""Social, trabalho, meio ambiente, viagens, fundo eleitoral e tarifa de energia: leitura dos arquivos (formato real) e rotas."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.collectors import ambiente, economia_extra as ex, social
from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import Municipio, Registro

BOLSA = ('"MÊS COMPETÊNCIA";"MÊS REFERÊNCIA";"UF";"CÓDIGO MUNICÍPIO SIAFI";"NOME MUNICÍPIO";"CPF FAVORECIDO";"NIS FAVORECIDO";"NOME FAVORECIDO";"VALOR PARCELA"\n'
         '"202609";"202609";"MG";"5155";"SANTA LUZIA";"";"12985893129";"FULANO";"600,00"\n'
         '"202609";"202609";"MG";"5155";"SANTA LUZIA";"";"2";"BELTRANO";"650,00"\n'
         '"202609";"202601";"AL";"2741";"COLONIA LEOPOLDINA";"";"3";"CICLANO";"600,00"\n'
         '"202609";"202609";"AL";"2741";"COLONIA LEOPOLDINA";"";"4";"OUTRO";"700,00"\n')


def _csv(texto):
    import csv
    import io
    leitor = csv.reader(io.StringIO(texto), delimiter=";")
    return next(leitor), leitor


def test_beneficios_contam_so_o_mes_e_nao_guardam_pessoas():
    ag = social.agregar_beneficios(*_csv(BOLSA))
    assert ag["_linhas"] == 4 and ag["MG"]["n"] == 2 and ag["MG"]["valor"] == 1250.0
    assert ag["AL"]["n"] == 1 and ag["AL"]["retroativo"] == 600.0  # parcela atrasada fica à parte
    assert ag["MG"]["municipios"]["5155"] == {"nome": "SANTA LUZIA", "n": 2, "valor": 1250.0}
    assert "FULANO" not in str(ag)


def test_beneficios_arquivo_cortado_ou_mudado(tmp_path):
    ag = social.agregar_beneficios(*_csv(BOLSA))
    with pytest.raises(RuntimeError, match="nada foi gravado"):
        social._guardar(None, "bolsa_familia_uf", "202609", "novo-bolsa-familia", ag, 5_000_000)
    with pytest.raises(ValueError, match="mudou"):
        social.agregar_beneficios(["A", "B"], [])


def test_viagens_somam_por_orgao_sem_viajante():
    cab = ["Identificador", "Situação", "Código do órgão superior", "Nome do órgão superior", "CPF viajante", "Nome", "Valor diárias", "Valor passagens", "Valor devolução", "Valor outros gastos"]
    linhas = [["1", "Realizada", "52000", "Ministério da Defesa", "***.1-**", "PESSOA", "1.000,00", "500,00", "100,00", "0,00"],
              ["2", "Realizada", "52000", "Ministério da Defesa", "***.2-**", "PESSOA2", "200,00", "0,00", "0,00", "50,00"],
              ["3", "Realizada", "26000", "Ministério da Educação", "***.3-**", "PESSOA3", "10,00", "0,00", "0,00", "0,00"]]
    d = social.agregar_viagens(cab, linhas)
    assert d["viagens"] == 3 and d["orgaos"][0]["orgao"] == "Ministério da Defesa" and d["orgaos"][0]["gasto"] == 1650.0 and d["gasto"] == 1660.0
    assert "PESSOA" not in str(d)


def test_prodes_e_deter():
    linhas = [{"state": "TOCANTINS", "year": "2023", "area_km": "1.5", "main_class": "DESMATAMENTO"}, {"state": "TO", "year": "2023", "area_km": "0.5", "main_class": "desmatamento"},
              {"state": "PA", "year": "2024", "area_km": "10", "main_class": "DESMATAMENTO"}, {"state": "PA", "year": "2024", "area_km": "99", "main_class": "nuvem"},
              {"state": "PA", "year": "2005", "area_km": "7", "main_class": "DESMATAMENTO"}]
    por_uf, n = ambiente.somar_prodes(linhas)
    assert n == 5 and por_uf == {"TO": {"2023": 2.0}, "PA": {"2024": 10.0}}
    d = ambiente.somar_deter([{"uf": "PA", "view_date": "2026-09-14", "areamunkm": "0.5", "classname": "DESMATAMENTO_CR"}, {"uf": "PA", "view_date": "2026-09-20", "areamunkm": "1", "classname": "DEGRADACAO"},
                              {"uf": "MT", "view_date": "2026-09-02", "areamunkm": "2", "classname": "DESMATAMENTO_VEG"}])
    assert d["PA"]["2026-09"] == {"desmatamento": 0.5, "degradacao": 1.0} and d["MT"]["2026-09"]["desmatamento"] == 2.0


def test_sidra_fefc_e_tarifas():
    r = [{"NC": "Nível"}, {"D1C": "35", "D3C": "202602", "V": "6.1"}, {"D1C": "35", "D3C": "202601", "V": "6,3"}, {"D1C": "11", "D3C": "202602", "V": "..."}]
    assert ex.ler_sidra(r) == {"SP": {"202602": 6.1, "202601": 6.3}}
    fefc = ('"AA_ELEICAO";"SG_PARTIDO";"NR_PARTIDO";"DS_GENERO";"QT_CANDIDATO";"VR_PARTIDO_FEFC";"PE_CAND_PARTIDO_GENERO";"VR_REPASSE_MINIMO_COTA";"VR_TOTAL_RECEBIDO_FEFC";"PE_VALOR_FEFC_GENERO";"ST_RENUNCIA"\n'
            '2024;"AGIR";36;"Feminino";2468;"3421737,78";"33,99";"1163048,67";"1413257,55";"41,30";0\n2024;"AGIR";36;"Masculino";4794;"3421737,78";"66,01";"2258689,11";"1794102,48";"52,43";0\n')
    p = ex.ler_fefc(fefc)
    assert p == [{"partido": "AGIR", "valor": 3421737.78, "candidatos": 7262, "mulheres": 2468, "valor_mulheres": 1413257.55}]
    linhas = [{"SigAgente": "CPFL", "NumCNPJDistribuidora": "1", "DatInicioVigencia": "2025-01-01", "DatFimVigencia": "2025-12-31", "DscBaseTarifaria": "Tarifa de Aplicação", "DscSubGrupo": "B1",
               "DscModalidadeTarifaria": "Convencional", "DscClasse": "Residencial", "DscSubClasse": "Residencial", "DscDetalhe": "Não se aplica", "VlrTUSD": "300,00", "VlrTE": "400,00"},
              {"SigAgente": "CPFL", "DatInicioVigencia": "2020-01-01", "DatFimVigencia": "2020-12-31", "DscBaseTarifaria": "Tarifa de Aplicação", "DscSubGrupo": "B1", "DscModalidadeTarifaria": "Convencional",
               "DscClasse": "Residencial", "DscSubClasse": "Residencial", "DscDetalhe": "Não se aplica", "VlrTUSD": "1,00", "VlrTE": "1,00"},
              {"SigAgente": "X", "DatInicioVigencia": "2025-01-01", "DatFimVigencia": "", "DscBaseTarifaria": "Base Econômica", "DscSubGrupo": "B1", "DscModalidadeTarifaria": "Convencional",
               "DscClasse": "Residencial", "DscSubClasse": "Residencial", "DscDetalhe": "Não se aplica", "VlrTUSD": "1,00", "VlrTE": "1,00"}]
    t = ex.ler_tarifas(linhas, hoje=date(2025, 6, 1))
    assert len(t) == 1 and t[0]["distribuidora"] == "CPFL" and t[0]["total"] == 0.7


def test_rotas_social_ambiente_e_demais():
    criar_tabelas()
    cliente = TestClient(app)
    from app.utils import _MEMO
    with SessionLocal() as db:
        db.query(Registro).filter(Registro.fonte.in_(["transparencia", "inpe", "ibge", "tse", "aneel"]), Registro.tipo.in_(
            ["bolsa_familia_uf", "bpc_uf", "viagens_ano", "prodes_bioma", "deter_bioma", "trabalho_desocupacao", "trabalho_rendimento", "fefc_ano", "tarifas_residencial"])).delete(synchronize_session=False)
        db.query(Municipio).filter(Municipio.codigo_ibge.in_(["3999001"])).delete()
        db.add(Municipio(codigo_ibge="3999001", nome="Santa Luzia", uf="MG", populacao=1000))
        db.commit()
    _MEMO.clear()
    for rota in ("/social", "/trabalho", "/ambiente", "/viagens", "/fundos", "/energia-tarifas"):
        assert cliente.get(rota).status_code == 404
    ag = social.agregar_beneficios(*_csv(BOLSA))
    ag.pop("_linhas")
    with SessionLocal() as db:
        for uf, e in ag.items():
            mun = [{"codigo": c, **m, "valor": m["valor"]} for c, m in e["municipios"].items()]
            db.add(Registro(fonte="transparencia", tipo="bolsa_familia_uf", chave=uf, dados={"mes": "202609", "n": e["n"], "valor": e["valor"], "retroativo": e["retroativo"], "municipios": mun}))
        db.add(Registro(fonte="inpe", tipo="prodes_bioma", chave="amazonia", dados={"bioma": "Amazônia", "ultimo_ano": "2024", "total": {"2023": 5.0, "2024": 10.0}, "por_uf": {"PA": {"2023": 5.0, "2024": 10.0}}}))
        db.add(Registro(fonte="inpe", tipo="prodes_bioma", chave="cerrado", dados={"bioma": "Cerrado", "ultimo_ano": "2024", "total": {"2024": 4.0}, "por_uf": {"PA": {"2024": 4.0}, "MT": {"2024": 4.0}}}))
        db.add(Registro(fonte="inpe", tipo="deter_bioma", chave="amazonia", dados={"bioma": "Amazônia", "desde": "2024-11-01", "por_uf": {"PA": {"2026-09": {"desmatamento": 3.0, "degradacao": 1.0}}}}))
        db.add(Registro(fonte="ibge", tipo="trabalho_desocupacao", chave="SP", dados={"rotulo": "Taxa de desocupação", "unidade": "%", "ultimo": "202602", "serie": {"202601": 6.3, "202602": 6.1}}))
        db.add(Registro(fonte="tse", tipo="fefc_ano", chave="2024", dados={"ano": 2024, "partidos": [{"partido": "AGIR", "valor": 3.0}]}))
        db.add(Registro(fonte="aneel", tipo="tarifas_residencial", chave="BR", dados={"data": "2026-10-30", "distribuidoras": [{"distribuidora": "CPFL", "total": 0.7}]}))
        db.add(Registro(fonte="transparencia", tipo="viagens_ano", chave="2025", dados={"ano": 2025, "viagens": 3, "gasto": 10.0, "orgaos": [{"orgao": "X", "gasto": 10.0}]}))
        db.commit()
    try:
        _MEMO.clear()
        s = cliente.get("/social").json()
        assert s["estados"]["MG"]["bolsa"]["beneficiarios"] == 2 and s["estados"]["MG"]["bolsa"]["por_100_hab"] == pytest.approx(2 / s["estados"]["MG"]["populacao"] * 100, abs=0.01)
        assert cliente.get("/social/municipios?uf=MG").json()["itens"][0]["bolsa"] == 2
        a = cliente.get("/ambiente").json()
        assert a["brasil"]["2024"] == 18.0 and a["estados"]["PA"]["km2"] == 14.0 and a["estados"]["PA"]["por_bioma"] == {"Amazônia": 10.0, "Cerrado": 4.0} and a["estados"]["PA"]["deter_12m"] == 3.0
        assert cliente.get("/trabalho").json()["estados"]["SP"]["desocupacao"] == 6.1
        assert cliente.get("/viagens").json()["anos"][0]["ano"] == 2025 and cliente.get("/fundos").json()["anos"]["2024"]["partidos"][0]["partido"] == "AGIR"
        assert cliente.get("/energia-tarifas").json()["distribuidoras"][0]["distribuidora"] == "CPFL"
    finally:
        with SessionLocal() as db:
            db.query(Registro).filter(Registro.tipo.in_(["bolsa_familia_uf", "bpc_uf", "viagens_ano", "prodes_bioma", "deter_bioma", "trabalho_desocupacao", "trabalho_rendimento", "fefc_ano", "tarifas_residencial"])).delete(synchronize_session=False)
            db.query(Municipio).filter(Municipio.codigo_ibge == "3999001").delete()
            db.commit()
        _MEMO.clear()
