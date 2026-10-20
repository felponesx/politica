"""Assembleias Legislativas com respostas simuladas."""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

from datetime import date  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from app import http  # noqa: E402
from app.collectors import assembleias  # noqa: E402
from app.db import criar_tabelas  # noqa: E402
from app.main import app  # noqa: E402

criar_tabelas()
cliente = TestClient(app)

ALESP_DEP = """<?xml version="1.0" encoding="UTF-8"?><Deputados>
<Deputado><IdDeputado>901</IdDeputado><NomeParlamentar>Fulana Paulista</NomeParlamentar><Partido>PSDB</Partido><Situacao>EXE</Situacao><Email>f@al.sp.gov.br</Email></Deputado>
<Deputado><IdDeputado>902</IdDeputado><NomeParlamentar>Beltrano Bandeirante</NomeParlamentar><Partido>PT</Partido><Situacao>EXE</Situacao></Deputado>
</Deputados>""".encode()
ALESP_VOT = """<?xml version="1.0" encoding="UTF-8"?><Votacoes>
<Votacao><IdDeliberacao>55</IdDeliberacao><Data>2026-10-01T10:00:00</Data><SiglaComissao>CCJR</SiglaComissao><IdDeputado>901</IdDeputado><Voto>Favorável</Voto><NumeroDocumento>PL 100/2026</NumeroDocumento></Votacao>
<Votacao><IdDeliberacao>55</IdDeliberacao><Data>2026-10-01T10:00:00</Data><SiglaComissao>CCJR</SiglaComissao><IdDeputado>902</IdDeputado><Voto>Contrário</Voto><NumeroDocumento>PL 100/2026</NumeroDocumento></Votacao>
</Votacoes>""".encode()


class R:
    def __init__(self, c):
        self.content = c


def test_assembleias_sp_mg(monkeypatch):
    monkeypatch.setattr(http, "get", lambda url, params=None, headers=None: R(ALESP_DEP if "deputados" in url else ALESP_VOT))

    def almg(url, params=None, headers=None):
        if url.endswith("/deputados/em_exercicio"):
            return {"list": [{"id": 1, "nome": "Deputada Mineira", "partido": "PL"}, {"id": 2, "nome": "Deputado Gerais", "partido": "PT"}]}
        if url.endswith("/reunioes/pesquisa"):
            return {"resultado": {"listaItem": [{"dataReuniao": "2026-10-02", "horario": "14:00"}]}}
        if "/plenario/reunioes/2026/10/02/14:00" in url:
            return {"descricao": "Reunião ordinária", "votacoes": [{"votos": [{"nome": "Deputada Mineira", "voto": "Sim"},
                                                                                {"nome": "Deputado Gerais", "voto": "Não"}]}]}
        raise AssertionError(url)
    monkeypatch.setattr(http, "get_json", almg)
    assert assembleias.coletar_assembleias(inicio=date(2026, 9, 1), fim=date(2026, 10, 8)) >= 6
    sp = cliente.get("/parlamentares?casa=al-sp").json()
    assert sp["total"] == 2 and sp["itens"][0]["uf"] == "SP"
    v = cliente.get("/votacoes?casa=al-sp").json()["itens"][0]
    d = cliente.get(f"/votacoes/{v['id']}").json()
    assert d["placar"] == {"Sim": 1, "Não": 1} and v["orgao"] == "CCJR"
    vm = cliente.get("/votacoes?casa=al-mg").json()["itens"][0]
    assert cliente.get(f"/votacoes/{vm['id']}").json()["placar"] == {"Sim": 1, "Não": 1}
    a = cliente.get("/assembleias").json()
    assert a["SP"]["deputados"] == 2 and a["MG"]["votacoes"] == 1


def test_assembleia_por_planilha(tmp_path):
    f = tmp_path / "alba.csv"
    f.write_text("Nome Parlamentar;Partido;E-mail\nDeputado Baiano;PSD;b@al.ba.gov.br\nDeputada Soteropolitana;PT;\n", encoding="utf-8")
    assert assembleias.importar_deputados_arquivo("BA", str(f)) == 2
    assert cliente.get("/parlamentares?casa=al-ba").json()["total"] == 2
    assert assembleias.normalizar_voto("NÃO") == "Não" and assembleias.normalizar_voto("abstenção") == "Abstenção"


def test_malhas_e_mapa(monkeypatch):
    from app.collectors import malhas
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"codarea": "3550308"}, "geometry": {"type": "Polygon", "coordinates": [[[-46.8, -23.4], [-46.4, -23.4], [-46.4, -23.8], [-46.8, -23.4]]]}},
        {"type": "Feature", "properties": {"codarea": "3509502"}, "geometry": {"type": "MultiPolygon", "coordinates": [[[[-47.2, -22.8], [-46.9, -22.8], [-47.0, -23.0], [-47.2, -22.8]]]]}}]}
    monkeypatch.setattr(http, "get_json", lambda url, params=None, headers=None: gj)
    assert malhas.coletar_malhas(ufs=["SP"]) == 1
    m = cliente.get("/malhas/SP").json()
    assert m["largura"] == 600 and {x["codigo"] for x in m["municipios"]} == {"3550308", "3509502"}
    assert m["municipios"][0]["d"].startswith("M") and cliente.get("/malhas/AC").status_code == 404
    e = cliente.get("/mapa/estados").json()
    assert set(e["estados"]) >= {"SP", "RJ"} and isinstance(e["metricas"], list)


def test_setores_cnae():
    from app.db import SessionLocal
    from app.models import EmpresaCadastro
    from app.setores import setor_de_cnae
    assert setor_de_cnae("4120400") == "Construção civil" and setor_de_cnae("6201501") == "Tecnologia"
    assert setor_de_cnae("4644301") == "Saúde" and setor_de_cnae("8121400") == "Limpeza e conservação"
    assert setor_de_cnae("8011101") == "Segurança" and setor_de_cnae("5611201") == "Alimentação" and setor_de_cnae(None) == "Outros"
    db = SessionLocal()
    db.query(EmpresaCadastro).filter(EmpresaCadastro.cnpj == "55444333000122").delete()  # o banco de teste fica entre execuções
    db.add(EmpresaCadastro(cnpj="55444333000122", razao_social="TECNO TESTE LTDA", cnae="6201501", uf="SP", socios=[]))
    db.commit()
    db.close()
    s = {x["setor"]: x["empresas"] for x in cliente.get("/empresas-setores").json()}
    assert s["Tecnologia"] >= 1
    r = cliente.get("/empresas?setor=Tecnologia").json()
    assert any(i["cnpj"] == "55444333000122" for i in r["itens"])


def test_tramitacao_senado(monkeypatch):
    from app.collectors import congresso_extra

    def falso(url, params=None, headers=None):
        if "movimentacoes" in url:
            return {"MovimentacaoMateria": {"Materia": {"Tramitacoes": {"Tramitacao": [
                {"IdentificacaoTramitacao": {"DataTramitacao": "2026-05-02", "TextoTramitacao": "Leitura em plenário",
                                             "OrigemTramitacao": {"Local": {"SiglaLocal": "PLEN"}}}},
                {"IdentificacaoTramitacao": {"DataTramitacao": "2026-06-10", "TextoTramitacao": "Aprovado na CCJ",
                                             "OrigemTramitacao": {"Local": {"SiglaLocal": "CCJ"}},
                                             "Situacao": {"DescricaoSituacao": "Pronta para o Plenário"}}}]}}}}
        if "autoria" in url:
            return {"AutoriaMateria": {"Materia": {"Autoria": {"Autor": [{"NomeAutor": "Senador Exemplo", "SiglaTipoAutor": "SENADOR",
                                                                          "IdentificacaoParlamentar": {"CodigoParlamentar": "5901"}}]}}}}
        raise AssertionError(url)
    monkeypatch.setattr(http, "get_json", falso)
    passos, autores = congresso_extra.tramitacao_senado("123")
    assert [p["orgao"] for p in passos] == ["PLEN", "CCJ"] and passos[-1]["situacao"] == "Pronta para o Plenário"
    assert autores[0]["id_externo"] == "5901" and autores[0]["casa"] == "senado"
