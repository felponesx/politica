"""Concursos estaduais e municipais, e contratações de eventos no PNCP: cada coletor com respostas no formato real das fontes."""
import json
from datetime import date

import pytest
from sqlalchemy import delete

from app.collectors import concursos_estaduais as ce
from app.collectors import oportunidades as op
from app.db import SessionLocal, criar_tabelas
from app.models import Registro

TIPOS = ("concurso", "concurso_uf_status", "concursos_status", "cobertura", "evento_show", "pncp_pendencia")


class Resp:
    def __init__(self, dados=None, status=200, texto=None):
        self._d, self.status_code, self._t = dados, status, texto

    def json(self):
        if self._t is not None:
            return json.loads(self._t)  # página defeituosa: JSONDecodeError, como no PNCP de 15/09 e 11/11
        return self._d

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=None, response=None)


@pytest.fixture
def db():
    criar_tabelas()
    s = SessionLocal()
    s.execute(delete(Registro).where(Registro.tipo.in_(TIPOS)))
    s.commit()
    yield s
    s.execute(delete(Registro).where(Registro.tipo.in_(TIPOS)))
    s.commit()
    s.close()


# ------------------------------------------------------------------------------------------------ classificação
def test_tipo_de_ato_e_area():
    assert op.classificar_ato("EDITAL DE CONCURSO PÚBLICO Nº DP-4/321/26 A Diretoria de Pessoal da Polícia Militar torna pública a abertura "
                              "das inscrições do concurso público para provimento de cargos de Soldado") == "abertura"
    assert op.classificar_ato("COMUNICADO DP - 157/323/26 O Diretor de Pessoal CONVOCA os candidatos inscritos no Concurso Público") == "convocacao"
    assert op.classificar_ato("ATO Nº 2.413/2026. O GOVERNADOR resolve nomear os candidatos aprovados no concurso público") == "nomeacao"
    assert op.classificar_ato("Edital de Classificação nº DP - 3/323/26 torna pública a Classificação Final do Concurso") == "homologacao"
    assert op.classificar_ato("EDITAL Nº 196 retificação do concurso público para Professor") == "retificacao"
    assert op.classificar_ato("ORDEM DO DIA PARA A 169ª SESSÃO ORDINÁRIA - abertura da sessão; concurso") == "outro"
    assert op.area_concurso("concurso para Soldado da Polícia Militar do Estado") == "Polícia Militar"
    assert op.area_concurso("Delegado de Polícia da Polícia Civil") == "Polícia Civil"
    assert op.area_concurso("Policial Penal - sistema prisional") == "Polícia Penal"
    assert op.area_concurso("concurso de PROFESSOR DOUTOR na Faculdade de Direito") == "Educação"


# ------------------------------------------------------------------------------------------------ estaduais
SP_BUSCA = {"items": [{"id": "93f2e749", "date": "2026-11-03T01:03:33", "title": "ABERTURA - CONCURSO Nº 229/2026, DE 29 DE OUTUBRO DE 2026",
                       "slug": "executivo/universidade-estadual-paulista/abertura-concurso-n-229-2026",
                       "excerpt": "as inscrições para o concurso público de provas e títulos para provimento de 1 cargo de PROFESSOR TITULAR",
                       "hierarchy": "Executivo > Atos de Gestão e Despesas > Universidade Estadual Paulista > Campus de Marília"}]}
SP_DETALHE = {"content": "<p>EDITAL No 229/2026</p><p>Acham-se abertas as inscrições para o concurso público para provimento de 1 (um) cargo de "
                         "PROFESSOR TITULAR. A remuneração é de R$ 19.880,54. As inscrições serão realizadas de 04/11/2026 a 03/12/2026.</p>"}


def test_sp_le_busca_e_texto_completo(db, monkeypatch):
    def falso(cli, url, **kw):
        if "advanced-search" in url:
            return Resp(SP_BUSCA if kw["params"]["Terms[0]"] == "concurso público" else {"items": []})
        return Resp(SP_DETALHE)
    monkeypatch.setattr(ce, "_get", falso)
    st = ce.coletar_estado(db, None, "SP", dias=15)
    assert st["status"] == "ok" and st["itens"] == 1 and st["ultima_sucesso"]
    d = db.query(Registro).filter_by(fonte="doe_sp", tipo="concurso").one().dados
    assert d["ato"] == "abertura" and d["orgao"] == "Universidade Estadual Paulista" and d["area"] == "Educação"
    assert d["salario_max"] == 19880.54 and d["inscricoes_fim"] == "2026-12-03"
    assert "vagas" not in d and d["incompleto"] == ["vagas"]  # o texto diz "1 cargo", não "vagas": nada é deduzido
    assert d["url"].startswith("https://doe.sp.gov.br/") and d["publicado"] == "2026-11-03" and d["coletado_em"] and d["primeira_coleta"]
    primeira = d["primeira_coleta"]
    ce.coletar_estado(db, None, "SP", dias=15)  # de novo: sem duplicar e sem perder a primeira coleta
    assert db.query(Registro).filter_by(fonte="doe_sp", tipo="concurso").count() == 1
    assert db.query(Registro).filter_by(fonte="doe_sp", tipo="concurso").one().dados["primeira_coleta"] == primeira


DIOE = {"hits": {"hits": [{"_source": {"data": "2026-11-11", "pagina": "141", "diario_id": "19430", "conteudo":
        "Diário Oficial 12 de novembro de 2026 SECRETARIA DE ESTADO DE SEGURANÇA PÚBLICA EDITAL Nº 01/2026 - PJC. O Secretário torna pública a "
        "abertura das inscrições do concurso público para provimento de cargos de Delegado de Polícia da Polícia Civil, com 50 vagas. "
        "A remuneração inicial é de R$ 25.000,00."}}]}}


def test_plataforma_comum_mt_e_falha_preserva_ultima_coleta(db, monkeypatch):
    monkeypatch.setattr(ce, "_get", lambda cli, url, **kw: Resp(DIOE if kw["params"]["q"] == '"concurso público"' else {"hits": {"hits": []}}))
    st = ce.coletar_estado(db, None, "MT", dias=15)
    assert st["status"] == "ok" and st["itens"] == 1
    d = db.query(Registro).filter_by(fonte="doe_mt", tipo="concurso").one().dados
    assert d["ato"] == "abertura" and d["area"] == "Polícia Civil" and d["vagas"] == 50 and d["salario_max"] == 25000
    assert d["url"] == "https://www.iomat.mt.gov.br/portal/edicoes/download/19430/141"
    boa = st["ultima_sucesso"]

    def fora(cli, url, **kw):
        raise ce.httpx.ConnectTimeout("sem resposta")
    monkeypatch.setattr(ce, "_get", fora)
    st = ce.coletar_estado(db, None, "MT", dias=15)
    assert st["status"] == "indisponivel" and st["ultima_sucesso"] == boa and "ConnectTimeout" in st["erro"]
    assert db.query(Registro).filter_by(fonte="doe_mt", tipo="concurso").count() == 1  # o que já tinha continua
    assert [h["status"] for h in st["historico"]] == ["ok", "indisponivel"]


def test_estado_sem_coletor_fica_registrado_com_motivo(db):
    st = ce.coletar_estado(db, None, "BA")
    assert st["status"] == "sem_coletor" and st["motivo"] and st["itens"] == 0
    assert len(ce.REGISTRO) == 27 and {r[0] for r in ce.REGISTRO} == set(__import__("app.utils", fromlist=["UFS"]).UFS)


# ------------------------------------------------------------------------------------------------ municipais (Querido Diário)
CIDADES = {"cities": [{"territory_id": "3550308", "territory_name": "São Paulo", "state_code": "SP", "level": "3"},
                      {"territory_id": "3509502", "territory_name": "Campinas", "state_code": "SP", "level": "3"}]}
GAZETAS = {"gazettes": [{"territory_id": "3509502", "territory_name": "Campinas", "state_code": "SP", "date": "2026-11-10",
                         "url": "https://queridodiario.ok.org.br/campinas/2026-11-10.pdf",
                         "excerpts": ["EDITAL DE ABERTURA Nº 01/2026 A Prefeitura torna pública a abertura das inscrições do concurso público para "
                                      "provimento de cargos de Guarda Municipal, 30 vagas.",
                                      "EDITAL DE CONVOCAÇÃO Nº 12 convoca os candidatos aprovados no concurso público 01/2024",
                                      "PORTARIA Nº 55 resolve nomear os candidatos aprovados no concurso público 01/2024"]}]}


def test_querido_diario_atos_e_cobertura(db, monkeypatch):
    monkeypatch.setattr(op, "_qd_get", lambda cli, url, params=None: Resp(CIDADES if url.endswith("/cities") else
                                                                        (GAZETAS if params["querystring"] == '"concurso público"' else {"gazettes": []})))
    assert op._concursos_municipais(db, None, 7) == 3
    atos = sorted(r.dados["ato"] for r in db.query(Registro).filter_by(fonte="querido_diario", tipo="concurso"))
    assert atos == ["abertura", "convocacao", "nomeacao"]
    ab = next(r.dados for r in db.query(Registro).filter_by(fonte="querido_diario", tipo="concurso") if r.dados["ato"] == "abertura")
    assert ab["municipio"] == "Campinas" and ab["area"] == "Segurança" and ab["vagas"] == 30 and ab["trecho_apenas"]
    cob = db.query(Registro).filter_by(fonte="querido_diario", tipo="cobertura").one().dados
    assert cob["monitorados"] == 2 and "3509502" in cob["lista"]
    st = db.query(Registro).filter_by(fonte="querido_diario", tipo="concursos_status").one().dados
    assert st["status"] == "ok" and st["ultima_sucesso"]


def test_querido_diario_fora_do_ar_nao_vira_zero(db, monkeypatch):
    monkeypatch.setattr(op, "_qd_get", lambda cli, url, params=None: Resp(status=503))
    with pytest.raises(RuntimeError):
        op._concursos_municipais(db, None, 7)
    st = db.query(Registro).filter_by(fonte="querido_diario", tipo="concursos_status").one().dados
    assert st["status"] == "indisponivel" and "503" in st["erro"] and st["ultima_sucesso"] is None


def test_qd_tenta_de_novo(monkeypatch):
    chamadas = []

    class Cli:
        def get(self, url, params=None):
            chamadas.append(1)
            return Resp({"ok": 1}, status=503 if len(chamadas) < 3 else 200)
    monkeypatch.setattr(op.time, "sleep", lambda s: None)
    assert op._qd_get(Cli(), "x").status_code == 200 and len(chamadas) == 3


# ------------------------------------------------------------------------------------------------ eventos (PNCP)
def _compra(n, objeto, valor=10000.0, hom=True, srp=False, cnpj="111"):
    return {"numeroControlePNCP": f"c-{n}", "objetoCompra": objeto, "valorTotalHomologado": valor if hom else None, "valorTotalEstimado": valor,
            "srp": srp, "orgaoEntidade": {"cnpj": cnpj, "razaoSocial": "MUNICIPIO X", "esferaId": "M"},
            "unidadeOrgao": {"ufSigla": "BA", "municipioNome": "Feira de Santana", "nomeUnidade": "Cultura"},
            "anoCompra": 2026, "sequencialCompra": n, "dataPublicacaoPncp": "2026-11-11T10:00:00"}


def test_categorias_de_evento():
    assert op.categorias_evento("APRESENTAÇÃO ARTÍSTICA DA ATRAÇÃO DJALMA FERREIRA NO EVENTO MICARETA DE FEIRA 2026") == ["cache"]
    assert op.categorias_evento("Locação de palco, sonorização e iluminação para o Carnaval 2027") == ["palco", "som", "iluminacao"]
    assert op.categorias_evento("Contratação de empresa de segurança privada para o Festival de Inverno") == ["seguranca"]
    assert op.categorias_evento("Locação de banheiros químicos e tendas para a festa de São João") == ["estrutura"]
    assert op.categorias_evento("Produção executiva do evento Réveillon 2027") == ["producao"]
    assert op.categorias_evento("Contratação de empresa para iluminação pública do bairro") == []
    assert op.categorias_evento("Fretamento de ônibus executivos para o transporte dos integrantes da Banda Municipal ao festival") == []
    assert op.categorias_evento("AQUISIÇÃO DE ILUMINAÇÃO DECORATIVA NATALINA (CASCATAS LUMINOSAS DE LED) para o Natal") == []
    assert op.categorias_evento("Fornecimento de estandes, palco tipo tablado, sistema de sonorização e painel de LED, para evento") == ["palco", "som", "estrutura"]
    assert op.categorias_evento("Aquisição de material de limpeza") == []
    assert op.categorias_evento("CONTRATAÇÃO DO ESCRITÓRIO CENTRAL DE ARRECADAÇÃO E DISTRIBUIÇÃO - ECAD, PARA PAGAMENTO DOS DIREITOS AUTORAIS") == []
    # a produtora que representa a banda não vira "produção do evento"
    assert op.categorias_evento("Contratação da empresa VL Produtora Ltda, para apresentação da Banda Vera Loca") == ["cache"]


def test_pagina_defeituosa_vira_pendencia_e_e_recuperada(db, monkeypatch):
    estado = {"defeito": True}

    def pagina(cli, mod, dia, p):
        if p == 2 and estado["defeito"]:
            raise json.JSONDecodeError("Expecting value", "", 0)
        return {"totalPaginas": 3, "data": [_compra(p, f"SHOW MUSICAL DA BANDA {p} NO ANIVERSÁRIO DA CIDADE")]}
    monkeypatch.setattr(op, "_pagina_pncp", pagina)
    achados, falhas = op._eventos_do_dia(None, 9, date(2026, 9, 15))
    assert len(achados) == 2 and [f[0] for f in falhas] == [2]  # a página 3 foi lida mesmo com a 2 com defeito
    op._pendencia(db, 9, date(2026, 9, 15), 2, falhas[0][1])
    db.commit()
    estado["defeito"] = False

    class Cli:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(op, "_cli", lambda *a, **k: Cli())
    assert op.coletar_eventos_pendencias() == 1
    p = db.query(Registro).filter_by(fonte="pncp", tipo="pncp_pendencia").one()
    db.refresh(p)
    assert p.dados["resolvida"] and p.dados["tentativas"] == 1
    assert db.query(Registro).filter_by(fonte="pncp", tipo="evento_show", chave="c-2").count() == 1


def test_soma_so_contratacao_distinta_e_homologada(db):
    from app import oportunidades as api
    quando = "2026-11-12T00:00:00+00:00"
    for x in (_compra(1, "Show da Banda A no Carnaval", 100000),
              _compra(2, "Show da Banda A no Carnaval", 100000),            # republicação do mesmo contrato
              _compra(3, "Locação de palco e som para o Carnaval", 50000, srp=True),  # teto de ata
              _compra(4, "Show da Dupla B no Carnaval", 30000, hom=False),   # só estimado
              _compra(5, "Segurança privada para o Carnaval", 20000)):
        op._gravar_evento(db, x, 9, quando)
    db.commit()
    e = api.eventos(db)
    assert e["valor_total"] == 120000  # 100 mil (uma vez) + 20 mil da segurança
    assert e["fora_da_soma"] == {"estimado_sem_homologacao": 30000, "registro_precos_teto": 50000, "possiveis_duplicatas": 100000, "valor_a_conferir": 0}
    assert e["por_categoria"]["varios"]["qtd"] == 1 and e["por_categoria"]["seguranca"]["valor_contratado"] == 20000
    d = db.query(Registro).filter_by(fonte="pncp", tipo="evento_show", chave="c-1").one().dados
    assert d["url"] == "https://pncp.gov.br/app/editais/111/2026/1" and d["publicado"] == "2026-11-11" and d["coletado_em"] == quando


def test_pendencia_da_pagina_1_rele_o_dia_todo(db, monkeypatch):
    monkeypatch.setattr(op, "_pagina_pncp", lambda cli, mod, dia, p: {"totalPaginas": 3, "data": [_compra(10 + p, f"SHOW DA BANDA {p} NA FESTA")]})

    class Cli:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    monkeypatch.setattr(op, "_cli", lambda *a, **k: Cli())
    op._pendencia(db, 9, date(2026, 11, 11), 1, "RemoteProtocolError")
    db.commit()
    assert op.coletar_eventos_pendencias() == 3  # as 3 páginas do dia, não só a 1


def test_valor_alto_demais_sai_da_soma(db):
    from app import oportunidades as api
    op._gravar_evento(db, _compra(30, "Camarote institucional no evento Semana 2026", 399990000.0), 9, "2026-11-12T00:00:00+00:00")
    op._gravar_evento(db, _compra(31, "Show da Banda Calypso no Carnaval", 80000.0), 9, "2026-11-12T00:00:00+00:00")
    db.commit()
    e = api.eventos(db)
    assert e["valor_total"] == 80000 and e["fora_da_soma"]["valor_a_conferir"] == 399990000.0
    assert any(x.get("valor_a_conferir") for x in api.eventos(db, "BA")["itens"])
