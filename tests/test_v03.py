"""Fontes da versão 0.3 com respostas simuladas (sem internet)."""
import io
import os
import zipfile
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import http  # noqa: E402
from app.collectors import agenda, bcb, congresso_extra, tse_financas  # noqa: E402
from app.db import SessionLocal, criar_tabelas  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Candidato, CandidatoFinancas, Parlamentar, Proposicao, Registro  # noqa: E402

criar_tabelas()
cliente = TestClient(app)


def test_bcb_e_economia(monkeypatch):
    def falso(url, params=None, headers=None):
        if "sgs.432/" in url:
            return [{"data": "01/09/2026", "valor": "14.25"}, {"data": "30/09/2026", "valor": "14.50"}]
        if "sgs.13522/" in url:
            return [{"data": "01/09/2025", "valor": "5,10"}, {"data": "01/09/2026", "valor": "4,20"}]
        return []
    monkeypatch.setattr(http, "get_json", falso)
    assert bcb.coletar_series(anos=2, nomes=["selic", "ipca_12m"]) >= 3
    e = cliente.get("/economia?nomes=selic,ipca_12m").json()["series"]
    assert e["selic"]["ultimo"] == {"data": "2026-09", "valor": 14.5}  # diária: último do mês
    assert e["ipca_12m"]["ultimo"]["valor"] == 4.2 and e["ipca_12m"]["doze_meses_antes"]["valor"] == 5.1


def test_contadores():
    db = SessionLocal()
    for mes in (1, 2, 3):
        db.add(Registro(fonte="receita", tipo="arrecadacao_uf", chave=f"SP-2026-{mes}", uf="SP", ano=2026, valor=100e9,
                        dados={"mes": mes}))
    db.add(Registro(fonte="siconfi", tipo="despesa_funcao", chave="U-1-2025-Saúde-t", ano=2025, titulo="Saúde", valor=315.36e9,
                    dados={"esfera": "U", "liquidado": 315.36e9}))
    db.commit()
    db.close()
    c = cliente.get("/contadores").json()
    imp, gas = c["impostometro"], c["gastometro"]
    assert imp["meses"] == 3 and round(imp["por_segundo"]) == round(300e9 / (90 * 86400))
    assert gas["ano"] >= 2025 and gas["por_segundo"] > 0


def test_agenda(monkeypatch):
    hoje = date(2026, 10, 9)

    def falso(url, params=None, headers=None):
        if url.endswith("/eventos"):
            return {"dados": [{"id": 77, "descricao": "Sessão Deliberativa Extraordinária", "descricaoTipo": "Sessão Deliberativa",
                               "situacao": "Em Andamento", "dataHoraInicio": "2026-10-09T14:00",
                               "orgaos": [{"sigla": "PLEN"}], "localCamara": {"nome": "Plenário"}}], "links": []}
        if url.endswith("/pauta"):
            return {"dados": [{"titulo": "PL 1234/2026", "proposicao_": {"ementa": "Teste de pauta"}, "situacaoItem": "Em votação"}]}
        if "agenda/dia" in url:
            return {"AgendaPlenario": {"Sessoes": {"Sessao": [{"CodigoSessao": "9", "TipoSessao": "Deliberativa",
                                                                "HoraInicioSessao": "10:00", "SituacaoSessao": "Encerrada"}]}}}
        raise AssertionError(url)
    monkeypatch.setattr(http, "get_json", falso)
    assert agenda.coletar_agenda(hoje) == 2
    r = cliente.get("/agora/eventos?dia=2026-10-09").json()
    assert r["itens"][0]["ao_vivo"] and r["itens"][0]["pauta"][0]["proposicao"] == "Teste de pauta"
    assert {e["casa"] for e in r["itens"]} == {"camara", "senado"}


def test_tramitacao_atuacao_ceaps(monkeypatch):
    db = SessionLocal()
    dep = Parlamentar(casa="camara", id_externo="901", nome="Deputada Teste", partido="ABC", uf="SP")
    sen = Parlamentar(casa="senado", id_externo="5901", nome="Senador Exemplo", partido="XYZ", uf="RJ")
    prop = Proposicao(casa="camara", id_externo="3001", sigla_tipo="PL", numero="99", ano=2026, ementa="Teste")
    db.add_all([dep, sen, prop])
    db.commit()
    pid, dep_id, sen_id = prop.id, dep.id, sen.id
    db.close()

    def falso(url, params=None, headers=None):
        if url.endswith("/tramitacoes"):
            return {"dados": [{"sequencia": 1, "dataHora": "2026-02-01T10:00", "siglaOrgao": "PLEN", "descricaoTramitacao": "Apresentação",
                               "descricaoSituacao": None}, {"sequencia": 2, "dataHora": "2026-03-01T10:00", "siglaOrgao": "CCJC",
                                                            "descricaoTramitacao": "Parecer", "descricaoSituacao": "Aguardando Plenário"}]}
        if url.endswith("/autores"):
            return {"dados": [{"nome": "Deputada Teste", "tipo": "Deputado", "uri": "https://dadosabertos.camara.leg.br/api/v2/deputados/901"}]}
        if url.endswith("/orgaos"):
            return {"dados": [{"siglaOrgao": "CFT", "nomePublicacao": "Comissão de Finanças", "titulo": "Titular", "dataFim": None}]}
        if "/discursos" in url:
            return {"dados": [{"dataHoraInicio": "2026-09-01T15:00", "tipoDiscurso": "BREVES COMUNICAÇÕES", "sumario": "Fala de teste"}], "links": []}
        if "/comissoes" in url:
            return {"MembroComissaoParlamentar": {"Parlamentar": {"MembroComissoes": {"Comissao": [
                {"IdentificacaoComissao": {"SiglaComissao": "CAE", "NomeComissao": "Assuntos Econômicos"}, "DescricaoParticipacao": "Titular"}]}}}}
        if "despesas_ceaps" in url:
            return [{"codSenador": 5901, "nomeSenador": "SENADOR EXEMPLO", "mes": 3, "tipoDespesa": "Passagens", "fornecedor": "Cia Aérea",
                     "cpfCnpj": "11.222.333/0001-81", "valorReembolsado": 1500.5, "id": 1}]
        raise AssertionError(url)
    monkeypatch.setattr(http, "get_json", falso)
    assert congresso_extra.coletar_tramitacoes(limite=10) >= 1
    p = cliente.get(f"/proposicoes/{pid}").json()
    assert [t["orgao"] for t in p["tramitacao"]] == ["PLEN", "CCJC"] and p["autores"][0]["parlamentar_id"] == dep_id
    assert p["proposicao"]["situacao"] == "Aguardando Plenário"
    assert congresso_extra.coletar_atuacao() >= 2
    a = cliente.get(f"/parlamentares/{dep_id}/atuacao").json()
    assert a["comissoes"][0]["sigla"] == "CFT" and a["discursos_12_meses"] == 1 and pid in [x["proposicao_id"] for x in a["projetos_autoria"]]
    assert cliente.get(f"/parlamentares/{sen_id}/atuacao").json()["comissoes"][0]["sigla"] == "CAE"
    assert congresso_extra.coletar_ceaps(2026) == 1
    g = cliente.get(f"/parlamentares/{sen_id}").json()
    assert g["total_gasto"] == 1500.5


def test_tse_financas(tmp_path):
    bens = "SQ_CANDIDATO;SG_UF;DS_TIPO_BEM_CANDIDATO;DS_BEM_CANDIDATO;VR_BEM_CANDIDATO\n" \
           "250001;SP;Apartamento;Apto centro;500000,00\n250001;SP;Veículo;Carro;80000,00\n"
    zb = tmp_path / "bens.zip"
    with zipfile.ZipFile(zb, "w") as z:
        z.writestr("bem_candidato_2022_SP.csv", bens.encode("latin-1"))
    assert tse_financas.coletar_bens(2022, arquivo_local=str(zb)) == 1
    rec = "SQ_CANDIDATO;SG_UF;DS_FONTE_RECEITA;VR_RECEITA\n250001;SP;Fundo Especial;100000,00\n250001;SP;Outros Recursos;20000,00\n"
    desp = "SQ_CANDIDATO;SG_UF;DS_ORIGEM_DESPESA;VR_DESPESA_CONTRATADA\n250001;SP;Publicidade;90000,00\n"
    zc = tmp_path / "contas.zip"
    with zipfile.ZipFile(zc, "w") as z:
        z.writestr("receitas_candidatos_2022_SP.csv", rec.encode("latin-1"))
        z.writestr("despesas_contratadas_candidatos_2022_SP.csv", desp.encode("latin-1"))
    assert tse_financas.coletar_contas(2022, arquivo_local=str(zc)) == 1
    db = SessionLocal()
    f = db.query(CandidatoFinancas).filter_by(sq_candidato="250001").one()
    assert f.patrimonio == 580000 and f.receitas == 120000 and f.despesas == 90000
    assert f.bens[0]["tipo"] == "Apartamento" and f.receitas_por_fonte["Fundo Especial"] == 100000
    db.close()


def test_exportar_csv():
    lista = cliente.get("/exportar").json()
    assert any(c["conjunto"] == "parlamentares" for c in lista)
    r = cliente.get("/exportar/parlamentares.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    linhas = r.content.decode("utf-8-sig").splitlines()
    assert linhas[0].startswith("id;casa;") and len(linhas) >= 2
    assert cliente.get("/exportar/xyz.csv").status_code == 404


def test_bcb_pagina_de_erro_e_coleta_parcial(monkeypatch):
    """O SGS às vezes responde HTML no lugar do JSON: tenta de novo; série que não volta deixa a coleta 'parcial'."""
    from app.collectors import bcb
    from app.db import SessionLocal
    from app.models import Coleta
    chamadas = {"n": 0}

    def falso(url, params=None, headers=None):
        if "sgs.433/" in url:
            chamadas["n"] += 1
            if chamadas["n"] == 1:
                raise ValueError("Expecting value: line 1 column 1 (char 0)")  # página HTML de erro
            return [{"data": "01/08/2026", "valor": "0.2"}]
        raise ValueError("Expecting value")  # a outra série nunca volta

    monkeypatch.setattr(http, "get_json", falso)
    monkeypatch.setattr("time.sleep", lambda s: None)
    assert bcb.coletar_series(anos=1, nomes=["ipca_mes", "ipca_12m"]) >= 1
    with SessionLocal() as db:
        c = db.query(Coleta).filter_by(fonte="bcb").order_by(Coleta.id.desc()).first()
    assert c.status == "parcial" and "ipca_12m" in c.erro and "página de erro" in c.erro


def test_impostometro_soma_estados_e_municipios(monkeypatch):
    from app.collectors import siconfi
    from app.models import Municipio
    # Anexo 03 resumido (formato do SICONFI): linhas por conta e coluna; vale a coluna dos últimos 12 meses
    def anexo(esfera, id_ente):
        base = [("RREO3ImpostosTaxasEContribuicoesDeMelhoria", "Impostos, Taxas e Contribuições de Melhoria")]
        base += [("RREO3ICMS", "ICMS"), ("RREO3IPVA", "IPVA")] if esfera == "E" else [("RREO3ISS", "ISS"), ("RREO3IPTU", "IPTU")]
        tot = 300e9 if esfera == "E" else 20e9
        itens = []
        for cod, conta in base:
            v = tot if "Impostos" in conta else tot / 3
            itens += [{"instituicao": f"Ente {id_ente}", "cod_conta": cod, "conta": conta, "coluna": "<MR>", "valor": v / 12},
                      {"instituicao": f"Ente {id_ente}", "cod_conta": cod, "conta": conta, "coluna": "TOTAL (ÚLTIMOS 12 MESES)", "valor": v}]
        return {"items": itens, "hasMore": False}
    monkeypatch.setattr(http, "get_json", lambda url, params=None, headers=None: anexo(params["co_esfera"], params["id_ente"]))
    t = siconfi.tributos_anexo03(anexo("E", 35)["items"])
    assert t["total"] == 300e9 and t["por_tributo"]["icms"] == 100e9
    db = SessionLocal()
    for cod, uf, pop in (("3550308", "SP", 12_000_000), ("3509502", "SP", 1_200_000)):
        if not db.query(Municipio).filter_by(codigo_ibge=cod).first():
            db.add(Municipio(codigo_ibge=cod, nome=cod, uf=uf, populacao=pop))
    db.commit()
    db.close()
    assert siconfi.coletar_tributos_entes(2025, esferas=["E"]) == 27
    assert siconfi.coletar_tributos_entes(2025, esferas=["M"], ufs=["SP"]) >= 2
    imp = cliente.get("/contadores").json()["impostometro"]
    assert imp["partes_ano"]["estadual"] == round(300e9 * 27, 2)
    assert imp["partes_ano"]["municipal"] >= 40e9 and "municipais" in imp["base"]
    assert imp["por_segundo"] > imp["partes_ano"]["federal"] / (365 * 24 * 3600)
