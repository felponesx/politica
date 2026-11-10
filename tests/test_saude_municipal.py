"""Saúde por município: leitos (CNES), cobertura vacinal (PNI/TabNet) e mínimo constitucional (SICONFI Anexo 14) — respostas reais resumidas (10/11/2026)."""
from datetime import datetime

from fastapi.testclient import TestClient

from app.collectors.saude_mun import somar_leitos, tabela_google
from app.collectors.siconfi import saude_minimo_anexo14
from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import Coleta, Municipio, Registro
from app.utils import upsert

# linha real do arquivo Leitos_json_2026.zip (s3 ckan.saude.gov.br/Leitos_SUS), campos de endereço cortados
LEITO = {"COMP": "202601", "REGIAO": "NORDESTE", "UF": "PE", "CO_IBGE": "260290", "MUNICIPIO": "CABODESANTOAGOSTINHO", "MOTIVO_DESABILITACAO": "",
         "CNES": "0000027", "DS_TIPO_UNIDADE": "HOSPITALGERAL", "LEITOS_EXISTENTES": "64", "LEITOS_SUS": "0", "UTI_TOTAL_EXIST": "0", "UTI_TOTAL_SUS": "0",
         "UTI_ADULTO_EXIST": "0", "UTI_ADULTO_SUS": "0", "UTI_PEDIATRICO_EXIST": "0", "UTI_PEDIATRICO_SUS": "0", "UTI_NEONATAL_EXIST": "0",
         "UTI_NEONATAL_SUS": "0", "UTI_QUEIMADO_EXIST": "0", "UTI_QUEIMADO_SUS": "0", "UTI_CORONARIANA_EXIST": "0", "UTI_CORONARIANA_SUS": "0"}

# resposta real do webtabx.exe?bd_pni/cpnibr.def (Penta, UF × Ano, 2021–2022), só algumas linhas
PNI = """data.addColumn('string','Unidade da Federação');
        data.addColumn('number','2021');
        data.addColumn('number','2022');
        data.addColumn('number',' Total');
        data.addRows([
           [" Total" ,{v: 71.5250007459 ,f: '71,53'} ,{v: 77.2408056036 ,f: '77,24'} ,{v: 74.3219251216 ,f: '74,32'} ]
         , ["11 Rondônia" ,{v: 74.4181744182 ,f: '74,42'} ,{v: 82.6691991627 ,f: '82,67'} ,{v: 78.4477046853 ,f: '78,45'} ]
         , ["12 Acre" ,{v: 62.3525798526 ,f: '62,35'} ,{v: 72.3418306697 ,f: '72,34'} ,{v: 67.1663165935 ,f: '67,17'} ]
         , ["53 Distrito Federal" ,{v: 73.1648672858 ,f: '73,16'} ,{v: 78.2805314906 ,f: '78,28'} ,{v: 75.626964039 ,f: '75,63'} ]
        ]);"""

# linhas reais do RREO Anexo 14 da Prefeitura de São Paulo, 6º bimestre de 2025 (apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo)
ANEXO14 = [
    {"instituicao": "Prefeitura Municipal de São Paulo - SP", "conta": "Despesas com Ações e Serviços Públicos de Saúde Executadas com Recursos de Impostos",
     "coluna": "Valor Apurado Até o Bimestre", "valor": 19751075346.31},
    {"instituicao": "Prefeitura Municipal de São Paulo - SP", "conta": "Despesas com Ações e Serviços Públicos de Saúde Executadas com Recursos de Impostos",
     "coluna": "% Mínimo a Aplicar no Exercício", "valor": 15},
    {"instituicao": "Prefeitura Municipal de São Paulo - SP", "conta": "Despesas com Ações e Serviços Públicos de Saúde Executadas com Recursos de Impostos",
     "coluna": "% Aplicado Até o Bimestre", "valor": 23.85},
]


def test_soma_leitos_por_municipio_e_mes():
    outro = {**LEITO, "CNES": "1", "LEITOS_EXISTENTES": "10", "LEITOS_SUS": "8", "UTI_TOTAL_EXIST": "4", "UTI_TOTAL_SUS": "3", "UTI_ADULTO_EXIST": "4", "UTI_ADULTO_SUS": "3"}
    fechado = {**LEITO, "CNES": "2", "MOTIVO_DESABILITACAO": "DESATIVADO", "LEITOS_EXISTENTES": "99"}
    s = somar_leitos([LEITO, outro, fechado])
    d = s[("260290", "202601")]
    assert d["hospitais"] == 2 and d["existentes"] == 74 and d["sus"] == 8 and d["uti_exist"] == 4 and d["uti_adulto_sus"] == 3


def test_le_tabela_do_tabnet():
    cols, linhas = tabela_google(PNI)
    assert cols == ["Unidade da Federação", "2021", "2022", " Total"]
    assert linhas[0][0] == "Total" and round(linhas[0][2], 2) == 77.24
    assert ["12 Acre", 62.3525798526, 72.3418306697, 67.1663165935] in linhas


def test_minimo_constitucional_do_anexo14():
    m = saude_minimo_anexo14(ANEXO14)
    assert m["pct_aplicado"] == 23.85 and m["pct_minimo"] == 15 and m["cumpriu"] and round(m["valor_asps"]) == 19751075346
    assert saude_minimo_anexo14([]) is None  # sem anexo: indisponível, nunca 0%
    assert saude_minimo_anexo14(ANEXO14[:1]) is None


def test_api_separa_zero_de_sem_dado():
    criar_tabelas()
    cli = TestClient(app)
    with SessionLocal() as db:
        for cod, nome in (("9900011", "Cidade Com Hospital"), ("9900021", "Cidade Sem Hospital")):
            upsert(db, Municipio, {"codigo_ibge": cod}, {"nome": nome, "uf": "AC", "populacao": 10000})
        upsert(db, Registro, {"fonte": "cnes", "tipo": "leitos_municipio", "chave": "990001"},
               {"uf": "AC", "valor": 30, "dados": {"existentes": 30, "sus": 20, "uti_exist": 5, "uti_sus": 4, "hospitais": 1, "competencia": "2026-09"}})
        upsert(db, Registro, {"fonte": "cnes", "tipo": "leitos_resumo", "chave": "BR"}, {"dados": {"existentes": 30, "competencia": "2026-09"}})
        upsert(db, Registro, {"fonte": "datasus", "tipo": "vacinacao_municipio", "chave": "990001"}, {"uf": "AC", "ano": 2022, "dados": {"ano": 2022, "cobertura": {"Penta": 81.5}}})
        upsert(db, Registro, {"fonte": "siconfi", "tipo": "saude_minimo", "chave": "M-9900011-2025"},
               {"uf": "AC", "ano": 2025, "valor": 18.2, "dados": {"id_ente": 9900011, "pct_aplicado": 18.2, "pct_minimo": 15, "cumpriu": True, "valor_asps": 1e6}})
        db.add(Coleta(fonte="cnes", tarefa="leitos_municipios", parametros={}, status="ok", inicio=datetime.now(), fim=datetime.now(), itens=1))
        db.commit()
    try:
        r = cli.get("/saude/municipios?uf=AC&limit=500").json()
        por = {x["codigo_ibge"]: x for x in r["itens"]}
        com, sem = por["990001"], por["990002"]
        assert com["leitos"] == 30 and com["leitos_sus"] == 20 and com["leitos_por_mil"] == 3.0 and com["vacinacao"]["Penta"] == 81.5
        assert com["saude_minimo_pct"] == 18.2 and com["saude_minimo_cumpriu"] is True
        # leitos coletados e município fora do arquivo = 0 cadastrados; vacinação e mínimo sem registro = sem dado (chave ausente, nunca 0)
        assert sem["leitos"] == 0 and "vacinacao" not in sem and "saude_minimo_pct" not in sem
        assert r["fontes"]["leitos"]["status"] == "ok" and r["fontes"]["leitos"]["periodo"] == "2026-09" and r["fontes"]["leitos"]["link"].startswith("https://")
        assert r["fontes"]["vacinacao"]["status"] == "nunca_coletada"
    finally:
        with SessionLocal() as db:
            db.query(Registro).filter(Registro.chave.in_(["990000", "BR", "M-9900011-2025"]), Registro.fonte.in_(["cnes", "datasus", "siconfi"])).delete(synchronize_session=False)
            db.query(Municipio).filter(Municipio.codigo_ibge.in_(["9900011", "9900021"])).delete(synchronize_session=False)
            db.query(Coleta).filter(Coleta.fonte == "cnes").delete(synchronize_session=False)
            db.commit()
