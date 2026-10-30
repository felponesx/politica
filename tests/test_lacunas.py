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


def test_anatel_soma_so_o_ultimo_mes_e_conta_fibra():
    from app.collectors import anatel
    linhas = ["Ano;Mês;Grupo Econômico;Empresa;CNPJ;Porte da Prestadora;UF;Município;Código IBGE Município;Faixa de Velocidade;Velocidade;Tecnologia;Meio de Acesso;Tipo de Pessoa;Tipo de Produto;Acessos",
              "2026;7;A;X;1;Grande;SP;Sao Paulo;1;>34;1;FTTH;Fibra;PF;INTERNET;100",
              "2026;8;A;X;1;Grande;SP;Sao Paulo;1;>34;1;FTTH;Fibra;PF;INTERNET;300",
              "2026;8;A;X;1;Grande;SP;Santos;2;>34;1;ETHERNET;Rádio;PF;INTERNET;100",
              "2026;8;A;X;1;Grande;AC;Rio Branco;3;>34;1;ETHERNET;Cabo Metálico;PF;INTERNET;50"]
    r = anatel.agregar(iter(linhas))
    assert r["mes"] == "2026-08" and r["ufs"]["SP"]["acessos"] == 400 and r["ufs"]["SP"]["fibra"] == 300 and r["ufs"]["AC"]["fibra"] == 0
    with pytest.raises(ValueError, match="colunas"):
        anatel.agregar(iter(["a;b", "1;2"]))


def test_anp_media_por_estado_so_do_ultimo_mes():
    from app.collectors import anp
    cab = "Regiao - Sigla;Estado - Sigla;Municipio;Revenda;CNPJ da Revenda;Nome da Rua;Numero Rua;Complemento;Bairro;Cep;Produto;Data da Coleta;Valor de Venda;Valor de Compra;Unidade de Medida;Bandeira\n"
    def l(uf, prod, data, v):
        return f"N;{uf};X;R; 01;;1;;;;{prod};{data};{v};;R$ / litro;B\n"
    txt = cab + l("AC", "GASOLINA", "02/12/2025", "9,00") + l("AC", "GASOLINA", "02/01/2026", "8,00") + l("AC", "GASOLINA", "09/01/2026", "6,00") + l("AC", "ETANOL", "09/01/2026", "5,00") + l("SP", "OLEO", "09/01/2026", "1,00")
    r = anp.agregar("﻿" + txt)
    assert r["mes"] == "2026-01" and r["ufs"]["AC"]["gasolina"] == {"preco": 7.0, "coletas": 2} and r["ufs"]["AC"]["etanol"]["preco"] == 5.0 and "SP" not in r["ufs"]
    assert anp.semestres_do_site('<a href="/x/ca/ca-2025-02.zip"></a><a href="/x/ca/ca-2026-01.zip"></a><a href="/x/ca/ca-2021-01.csv"></a>') == ["ca-2026-01.zip", "ca-2025-02.zip"]
    with pytest.raises(ValueError, match="colunas"):
        anp.agregar("a;b\n1;2\n")


def test_wfs_cai_para_sem_sortby_no_400_e_reduz_pagina_no_502(monkeypatch):
    chamadas = []

    class R:
        def __init__(self, t):
            self.text = t

    def falso(params):
        chamadas.append(dict(params))
        if "sortBy" in params:
            raise RuntimeError("HTTP 400 do WFS: Can handle 5 attributes only")
        if params["count"] == ambiente.PAGINA:
            raise RuntimeError("HTTP 502 do WFS: Falha interna")
        return R("FID,state\na,AC\nb,AM\n")

    monkeypatch.setattr(ambiente, "_pedido", falso)
    linhas = list(ambiente.paginas("c", "state"))
    assert [l["state"] for l in linhas] == ["AC", "AM"]
    assert "sortBy" not in chamadas[-1] and chamadas[-1]["count"] == ambiente.PAGINA // 2


def test_desmatamento_filtra_biomas_e_pula_deter(monkeypatch):
    lidos = []
    monkeypatch.setattr(ambiente, "total_feicoes", lambda camada, filtro=None: 1)

    def falso(camada, props, filtro=None, ordem="fid"):
        lidos.append((camada, props, ordem))
        yield {"state": "AC", "year": "2020", "area_km": "1.5", "main_class": "desmatamento"}

    monkeypatch.setattr(ambiente, "paginas", falso)
    criar_tabelas()
    ambiente.coletar_desmatamento(biomas="pantanal", deter="false")
    assert len(lidos) == 1 and lidos[0][0].startswith("prodes-pantanal") and lidos[0][1] is None and lidos[0][2] is None


def test_cpis_xml_do_senado_e_lista_ordenada(monkeypatch):
    from app.collectors import cpis
    xml = ("<ListaBasicaComissoes><Comissoes><Comissao><CodigoComissao>2500</CodigoComissao><SiglaComissao>CPIX</SiglaComissao><NomeComissao>CPI do Teste</NomeComissao>"
           "<DataInicio>2026-03-10</DataInicio></Comissao></Comissoes></ListaBasicaComissoes>")
    r = cpis.ler_xml_senado(xml)
    assert r == [{"id": "2500", "casa": "senado", "sigla": "CPIX", "nome": "CPI do Teste", "inicio": "2026-03-10", "fim": None, "situacao": "em atividade"}]
    criar_tabelas()
    from app import lacunas
    db = SessionLocal()
    try:
        from app.utils import upsert
        upsert(db, Registro, {"fonte": "congresso", "tipo": "cpis_casa", "chave": "camara"}, {"titulo": "x", "dados": {"itens": [{"id": 1, "nome": "Velha", "inicio": "2001-01-01"}, {"id": 2, "nome": "Nova", "inicio": "2025-01-01"}]}})
        db.commit()
        d = lacunas.cpis(db)
        assert [i["nome"] for i in d["itens"]][:2] == ["Nova", "Velha"] and "não prova" in d["aviso"]
    finally:
        db.rollback()
        db.close()


def test_anac_le_aerodromos_com_linha_de_data_e_acentos():
    from app.collectors import anac
    txt = ("Atualizado em: 2026-10-15\nCódigo OACI;CIAD;Nome;Município;UF;Município Servido;UF Servido;LATGEOPOINT;LONGEOPOINT;Latitude;Longitude;Altitude;Operação Diurna;Operação Noturna;Situação;Validade do Registro\n"
           "SBRB;AC0001;Plácido de Castro;RIO BRANCO;Acre;Rio Branco;Acre;-9.8;-67.8;a;b;193;VFR / IFR;VFR / IFR;Cadastrado;2030\n"
           "SDXX;SP0002;Pista;SANTOS;SP;Santos;SP;-23;-46;a;b;5;VFR;Não;Registrado;2029\n")
    r = anac.ler(txt)
    assert r["atualizado"] == "2026-10-15" and r["total"] == 2 and r["por_uf"]["AC"] == {"total": 1, "noturno": 1} and r["por_uf"]["SP"]["noturno"] == 0
    with pytest.raises(ValueError, match="colunas"):
        anac.ler("a;b\n1;2\n")


def test_ibama_soma_so_nao_cancelados_e_nao_guarda_nome():
    from app.collectors import ibama
    cab = "SEQ_AUTO_INFRACAO;SIT_CANCELADO;VAL_AUTO_INFRACAO;DAT_HORA_AUTO_INFRACAO;UF;TIPO_INFRACAO;NOME_INFRATOR\n"
    linhas = (cab + "1;N;1.000,50;2024-03-01 10:00:00;PA;Flora;FULANO\n2;S;9999,00;2024-04-01 10:00:00;PA;Flora;BELTRANO\n3;N;500,00;2025-01-05 00:00:00;MT;Pesca;CICLANO\n").splitlines()
    r = ibama.agregar(iter(linhas))
    assert r["lidos"] == 3 and r["cancelados"] == 1 and r["por_uf_ano"]["PA"]["2024"] == {"autos": 1, "valor": 1000.5} and r["por_tipo"]["Pesca"]["2025"] == 500.0
    assert "FULANO" not in str(r) and ibama.juntar([r, r])["por_uf_ano"]["PA"]["2024"]["autos"] == 2
    with pytest.raises(ValueError, match="colunas"):
        ibama.agregar(iter(["a;b", "1;2"]))


def test_lista_suja_so_totais_por_uf_e_ano():
    from app.collectors import trabalho_escravo as te
    txt = ("ID;Ano da ação fiscal;UF;Empregador;CNPJ/CPF;Estabelecimento;Trabalhadores envolvidos;CNAE;Decisão administrativa de procedência;Inclusão no Cadastro de Empregadores\n"
           "1;2024;SP;FULANO LTDA;41.297.068/0001-61;ROD X;2;4399-1/03;15/05/2025;06/10/2025\n2;2024;SP;OUTRO;48.937.720/0001-04;MT 235;5;2391-5/03;08/10/2024;09/04/2025\n3;2025;RS;TERCEIRO;1;R;3;1;1;1\n")
    r = te.ler(txt)
    assert r["total"] == 3 and r["trabalhadores"] == 10 and r["por_uf"]["SP"] == {"empregadores": 2, "trabalhadores": 7} and r["por_ano"]["2025"]["empregadores"] == 1
    assert "FULANO" not in str(r) and "41.297" not in str(r)


def test_renuncia_fiscal_le_quadro_1_e_acha_o_arquivo_mais_novo():
    from app.collectors import renuncia

    class Aba:
        def iter_rows(self, values_only=True):
            yield ("QUADRO I",)
            yield ("GASTOS TRIBUTÁRIOS - ESTIMATIVAS BASES EFETIVAS 2023 - POR FUNÇÃO ORÇAMENTÁRIA - REGIONALIZADO",)
            yield ("FUNÇÃO ORÇAMENTÁRIA", "NORTE", "NORDESTE", "CENTRO-OESTE", "SUDESTE", "SUL", "TOTAL")
            for k in range(12):
                yield (f"Função {k}", 1.0, 2.0, 3.0, 4.0, 5.0, 15.0)
            yield (None,)
            yield ("Depois", 9, 9, 9, 9, 9, 9)
    q = renuncia.ler_quadro1(Aba())
    assert q["ano_base"] == 2023 and len(q["funcoes"]) == 12 and q["funcoes"]["Função 0"]["centro_oeste"] == 3.0 and "Depois" not in q["funcoes"]
    html = '<a href="https://x/gastos-tributarios-bases-efetivas/dgt-bases-efetivas-2022-serie-2020-a-2025-quadros.xlsx/view"></a><a href="/y/dgt-bases-efetivas-2023-serie-2021-a-2026-quadros.xlsx/view"></a>'
    arqs = renuncia.arquivos_da_pagina(html)
    assert arqs[0][0] == 2023 and arqs[0][1].startswith("https://www.gov.br/y/") and arqs[0][1].endswith("quadros.xlsx")
