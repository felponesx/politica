"""Fontes da versão 0.2 com respostas e arquivos simulados (sem internet)."""
import os
import zipfile

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import http  # noqa: E402
from app.collectors import capag, cnpj, desastres, municipios, pgfn, siconfi  # noqa: E402
from app.db import SessionLocal, criar_tabelas  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Contrato, Registro  # noqa: E402

criar_tabelas()
cliente = TestClient(app)


def _ibge(url, params=None, headers=None):
    if url.endswith("/localidades/municipios"):
        return [{"id": 3550308, "nome": "São Paulo", "microrregiao": {"nome": "São Paulo", "mesorregiao": {"UF": {"sigla": "SP"}}}},
                {"id": 2927408, "nome": "Salvador", "microrregiao": {"nome": "Salvador", "mesorregiao": {"UF": {"sigla": "BA"}}}}]
    serie = lambda v1, v2, per: [{"unidade": "x", "resultados": [{"series": [
        {"localidade": {"id": "3550308"}, "serie": {per: v1}}, {"localidade": {"id": "2927408"}, "serie": {per: v2}}]}]}]
    if "/6579/" in url:
        return serie("11895578", "2568928", "2025")
    if "/5938/" in url:
        return serie("828980608", "66500000", "2021")
    if "/9543/" in url:
        return serie("97.5", "96.0", "2022")
    if "/4714/" in url:
        return serie("7528.26", "3859.44", "2022")
    raise AssertionError(url)


def test_municipios_e_indicadores(monkeypatch):
    monkeypatch.setattr(http, "get_json", _ibge)
    assert municipios.coletar_municipios() == 2
    assert municipios.coletar_indicadores_sociais() >= 2
    r = cliente.get("/municipios?uf=SP").json()
    assert r["itens"][0]["nome"] == "São Paulo" and r["itens"][0]["populacao"] == 11895578
    assert r["itens"][0]["pib"] == 828980608 * 1000
    d = cliente.get("/municipios/3550308").json()
    assert any(i["nome"] == "taxa_alfabetizacao" and i["valor"] == 97.5 for i in d["indicadores"])
    s = cliente.get("/indicadores-sociais?nome=taxa_alfabetizacao").json()
    assert s["media_por_uf"]["SP"] == 97.5


def test_indicador_por_arquivo(tmp_path):
    f = tmp_path / "idhm.csv"
    f.write_text("Código IBGE;Município;IDHM\n3550308;São Paulo;0,805\n292740;Salvador;0,759\n", encoding="latin-1")
    assert municipios.importar_indicador_arquivo(str(f), nome="idhm", descricao="IDHM", ano=2010) == 2
    s = cliente.get("/indicadores-sociais?nome=idhm").json()
    assert s["media_por_uf"] == {"SP": 0.805, "BA": 0.759}


def test_despesa_por_funcao(monkeypatch):
    linhas = [
        {"instituicao": "Governo do Estado de São Paulo", "conta": "Saúde", "coluna": "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)", "valor": 30e9},
        {"conta": "Saúde", "coluna": "DESPESAS EMPENHADAS ATÉ O BIMESTRE (b)", "valor": 32e9},
        {"conta": "Atenção Básica", "coluna": "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)", "valor": 1e9},
        {"conta": "Educação", "coluna": "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)", "valor": 40e9},
        {"conta": "Saúde", "coluna": "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)", "valor": 1e6},  # intraorçamentária
    ]
    monkeypatch.setattr(siconfi, "paginar", lambda ep, params: iter(linhas if params["co_esfera"] == "E" else []))
    assert siconfi.coletar_despesas_funcao(2025, esferas=["E"], ufs=["SP"]) == 2
    r = cliente.get("/gastos/funcao?esfera=E&uf=SP").json()
    assert r["ano"] == 2025 and r["funcoes"][0] == {"funcao": "Educação", "liquidado": 40e9, "empenhado": None, "dotacao": None}
    assert next(f for f in r["funcoes"] if f["funcao"] == "Saúde")["liquidado"] == 30e9
    assert cliente.get("/gastos/evolucao?esfera=E&uf=SP").json() == [{"ano": 2025, "liquidado": 70e9}]


def test_pgfn(tmp_path):
    csv = ("CPF_CNPJ;TIPO_PESSOA;TIPO_DEVEDOR;NOME_DEVEDOR;UF_DEVEDOR;UNIDADE_RESPONSAVEL;NUMERO_INSCRICAO;"
           "TIPO_SITUACAO_INSCRICAO;SITUACAO_INSCRICAO;RECEITA_PRINCIPAL;DATA_INSCRICAO;INDICADOR_AJUIZADO;VALOR_CONSOLIDADO\n"
           "11.222.333/0001-81;Pessoa jurídica;PRINCIPAL;EMPRESA GRANDE LTDA;SP;X;1;A;B;C;01/01/2020;SIM;1500000.50\n"
           "11.222.333/0001-81;Pessoa jurídica;PRINCIPAL;EMPRESA GRANDE LTDA;SP;X;2;A;B;C;01/01/2021;NAO;600000\n"
           "11.222.333/0001-81;Pessoa jurídica;CORRESPONSAVEL;EMPRESA GRANDE LTDA;SP;X;3;A;B;C;01/01/2021;NAO;999999\n"
           "44.555.666/0001-99;Pessoa jurídica;PRINCIPAL;PEQUENA ME;BA;X;4;A;B;C;01/01/2022;NAO;5000\n"
           "***.123.456-**;Pessoa física;PRINCIPAL;FULANO;BA;X;5;A;B;C;01/01/2022;NAO;20000\n")
    z = tmp_path / "pgfn.zip"
    with zipfile.ZipFile(z, "w") as f:
        f.writestr("arquivo_lai_SIDA_1_202502.csv", csv.encode("latin-1"))
    assert pgfn.coletar_divida_ativa(2025, 2, tipos=["nao_previdenciaria"], arquivo_local=str(z)) >= 4
    e = {x["uf"]: x for x in cliente.get("/dividas/estados").json()["estados"]}
    assert e["SP"]["pj"] == {"inscricoes": 2, "valor": 2100000.5} and e["BA"]["pf"]["inscricoes"] == 1
    d = cliente.get("/dividas/devedores").json()
    assert d["referencia"] == "2025T2" and [i["cnpj"] for i in d["itens"]] == ["11222333000181"]
    assert d["itens"][0]["valor_ajuizado"] == 1500000.5


def test_capag_e_empresa(tmp_path, monkeypatch):
    f = tmp_path / "capag.csv"
    f.write_text("Cod.IBGE;Nome_Município;UF;Indicador_1;Nota_1;CAPAG_Oficial;Ano_Base\n3550308;São Paulo;SP;0,5;A;A;2025\n"
                 "2927408;Salvador;BA;1,2;C;C;2025\n", encoding="utf-8")
    assert capag.coletar_capag(arquivo_local=str(f)) == 2
    r = cliente.get("/dividas/municipios").json()
    assert r["por_uf"] == {"SP": {"A": 1}, "BA": {"C": 1}} and r["ano"] == 2025
    # empresa: cadastro sob demanda só para CNPJ que está nas bases
    db = SessionLocal()
    reg = Registro(fonte="pncp", tipo="contrato", chave="t-1", uf="SP", ano=2025, valor=10, dados={})
    db.add(reg)
    db.flush()
    db.add(Contrato(registro_id=reg.id, fonte="pncp", numero_controle="t-1", cnpj_fornecedor="11222333000181",
                    fornecedor="EMPRESA GRANDE LTDA", valor=10, uf="SP"))
    db.commit()
    db.close()
    monkeypatch.setattr(http, "get_json_uma_vez", lambda url, **k: {
        "razao_social": "EMPRESA GRANDE LTDA", "cnae_fiscal": 4120400, "cnae_fiscal_descricao": "Construção de edifícios",
        "uf": "SP", "municipio": "SAO PAULO", "descricao_situacao_cadastral": "ATIVA", "data_inicio_atividade": "2001-05-10",
        "capital_social": 1000000, "qsa": [{"nome_socio": "SÓCIA EXEMPLO", "qualificacao_socio": "Sócio-Administrador",
                                            "cnpj_cpf_do_socio": "***123456**", "data_entrada_sociedade": "2001-05-10"}]})
    e = cliente.get("/empresas/11.222.333/0001-81").json()
    assert e["cadastro"]["razao_social"] == "EMPRESA GRANDE LTDA" and e["cadastro"]["socios"][0]["nome"] == "SÓCIA EXEMPLO"
    assert e["divida_ativa"][0]["valor"] == 2100000.5 and e["contratos_publicos"]["quantidade"] >= 1
    assert cliente.get("/empresas/99999999000199").status_code == 404
    assert cnpj.converter({"qsa": []})["socios"] == []


def test_desastres(tmp_path):
    f = tmp_path / "s2id.csv"
    f.write_text("UF;Município;Código IBGE;COBRADE;Descrição COBRADE;Data do Desastre;Status\n"
                 "BA;Salvador;2927408;13214;Chuvas Intensas;12/04/2024;Reconhecido\n"
                 "BA;Salvador;2927408;14110;Estiagem;01/09/2023;Reconhecido\n", encoding="utf-8")
    assert desastres.importar_desastres(arquivo_local=str(f)) == 2
    r = cliente.get("/riscos?uf=BA").json()
    assert r["municipios"][0]["ocorrencias"] == 2 and r["municipios"][0]["municipio"] == "Salvador"
    assert set(r["por_tipo"]) == {"Chuvas Intensas", "Estiagem"}


def test_composicao_e_orgaos():
    c = cliente.get("/partidos/composicao").json()
    assert set(c) == {"camara", "senado", "assembleia", "governador", "prefeito", "presidente"}
    db = SessionLocal()
    db.add(Registro(fonte="transparencia", tipo="orgao", chave="26000", titulo="Ministério da Educação", dados={}))
    db.add(Registro(fonte="transparencia", tipo="gasto_orgao", chave="g1", ano=2025, titulo="UFX", valor=5.0, dados={
        "codigoOrgaoSuperior": "26000", "orgaoSuperior": "Ministério da Educação", "codigoOrgao": "26231",
        "orgao": "Universidade X", "empenhado": "10,00", "liquidado": "8,00", "pago": "5,00"}))
    db.commit()
    db.close()
    o = cliente.get("/orgaos").json()
    assert o["itens"][0]["codigo"] == "26000" and o["itens"][0]["pago"] == 5.0
    d = cliente.get("/orgaos/26000").json()
    assert d["vinculados"][0]["nome"] == "Universidade X" and d["por_ano"][0]["empenhado"] == 10.0


def test_agendador_e_protecao(monkeypatch):
    from datetime import date

    from scripts import agendar
    g = agendar.grupos(date(2026, 10, 8))
    assert set(g) == {"agenda", "diario", "semanal", "mensal", "trimestral"}
    assert all(t in __import__("app.collectors", fromlist=["TAREFAS"]).TAREFAS for itens in g.values() for t, _ in itens)
    assert g["trimestral"][0][1] == {"ano": 2026, "trimestre": 3}
    assert agendar._trimestre_anterior(date(2026, 2, 1)) == (2025, 4)
    chamadas = []
    monkeypatch.setattr(agendar, "enviar", lambda t: chamadas.append(t))
    monkeypatch.setitem(agendar.TAREFAS, "ibge-indicadores", lambda **k: (_ for _ in ()).throw(RuntimeError("fora do ar")))
    monkeypatch.setattr(agendar, "grupos", lambda hoje=None: {"x": [("ibge-indicadores", {})]})
    for _ in range(3):
        agendar.rodar_grupo("x")
    assert len(chamadas) == 1 and "3 vezes" in chamadas[0]
    r = cliente.get("/")
    assert "Content-Security-Policy" in r.headers and r.headers["X-Content-Type-Options"] == "nosniff"


def test_candidatos_eleitos_da_casa():
    from app.models import Candidato
    db = SessionLocal()
    for i, (ano, cargo, res) in enumerate([(2022, "DEPUTADO ESTADUAL", "ELEITO POR QP"), (2022, "DEPUTADO DISTRITAL", "ELEITO POR MÉDIA"),
                                          (2022, "DEPUTADO ESTADUAL", "NÃO ELEITO"), (2018, "DEPUTADO ESTADUAL", "ELEITO"),
                                          (2024, "PREFEITO", "ELEITO")]):
        reg = Registro(fonte="tse", tipo="candidato_teste", chave=f"c{i}", dados={})
        db.add(reg)
        db.flush()
        db.add(Candidato(registro_id=reg.id, ano=ano, sq_candidato=f"x{i}", nome=f"Pessoa {i}", nome_urna=f"P{i}",
                         cargo=cargo, uf="DF" if "DISTRITAL" in cargo else "SP", resultado=res))
    db.commit()
    db.close()
    r = cliente.get("/candidatos?cargo=DEPUTADO ESTADUAL,DEPUTADO DISTRITAL&eleitos=true").json()
    assert sorted(c["nome_urna"] for c in r["itens"]) == ["P0", "P1"]
    assert [c["ano"] for c in cliente.get("/candidatos?cargo=PREFEITO&eleitos=true").json()["itens"]] == [2024]


SRU = """<?xml version="1.0"?>
<srw:searchRetrieveResponse xmlns:srw="http://www.loc.gov/zing/srw/" xmlns:dc="http://purl.org/dc/elements/1.1/"
  xmlns:srw_dc="info:srw/schema/1/dc-schema">
 <srw:numberOfRecords>2</srw:numberOfRecords>
 <srw:records>
  <srw:record><srw:recordData><srw_dc:dc>
   <urn>urn:lex:br;sao.paulo:estadual:lei:2025-03-10;18001</urn>
   <dc:title>Lei nº 18.001, de 10 de março de 2025</dc:title>
   <dc:description>Institui o programa estadual de teste.</dc:description>
  </srw_dc:dc></srw:recordData></srw:record>
  <srw:record><srw:recordData><srw_dc:dc>
   <urn>urn:lex:br;sao.paulo:estadual:lei.complementar:2025-06-01;1400</urn>
   <dc:title>Lei Complementar nº 1.400</dc:title>
  </srw_dc:dc></srw:recordData></srw:record>
 </srw:records>
</srw:searchRetrieveResponse>"""


def test_lexml_estaduais(monkeypatch):
    from app.collectors import lexml

    class Resp:
        text = SRU
    chamadas = []
    monkeypatch.setattr(http, "get", lambda url, params=None, headers=None: (chamadas.append(params), Resp())[1])
    assert lexml.localidade("SP") == "sao.paulo" and lexml.localidade("RN") == "rio.grande.do.norte"
    assert lexml.coletar_estaduais(2025, ufs=["SP"]) == 2
    assert "sao.paulo" in chamadas[0]["query"]
    r = cliente.get("/legislacao?esfera=estadual&uf=SP").json()
    assert {(n["tipo"], n["numero"]) for n in r["itens"]} == {("LEI", "18001"), ("LCP", "1400")}
    assert r["itens"][0]["esfera"] == "estadual"
    assert cliente.get("/legislacao-estados").json()["SP"]["normas"] == 2
    assert cliente.get("/legislacao?esfera=federal&uf=SP").json()["total"] == 0
