"""As 50 perguntas de treinamento: cada tipo de resposta, com dados de teste, e a tabela de cobertura conferida pergunta por pergunta."""
import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import busca, escandalos, ia_propria
from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import (Candidato, CandidatoFinancas, Despesa, Parlamentar, Proposicao, Registro, Voto, Votacao)

IDS = ["9901", "9902", "9903"]
COBERTURA = json.loads((Path(__file__).resolve().parent.parent / "app" / "dados" / "ia_cobertura.json").read_text(encoding="utf-8"))


def _limpar():
    with SessionLocal() as db:
        pids = db.scalars(select(Parlamentar.id).where(Parlamentar.id_externo.in_(IDS))).all()
        vids = db.scalars(select(Votacao.id).where(Votacao.id_externo.like("v99%"))).all()
        if vids:
            db.query(Voto).filter(Voto.votacao_id.in_(vids)).delete(synchronize_session=False)
            db.query(Votacao).filter(Votacao.id.in_(vids)).delete(synchronize_session=False)
        if pids:
            db.query(Despesa).filter(Despesa.parlamentar_id.in_(pids)).delete(synchronize_session=False)
            db.query(Candidato).filter(Candidato.parlamentar_id.in_(pids)).delete(synchronize_session=False)
        db.query(CandidatoFinancas).filter(CandidatoFinancas.sq_candidato.in_(["9901018", "9901022"])).delete(synchronize_session=False)
        db.query(Registro).filter(Registro.chave.in_(["9901-2018", "9901-2022", "emendas-2023"]) | Registro.chave.like("p99%")).delete(synchronize_session=False)
        db.query(Registro).filter(Registro.fonte == "ia").delete(synchronize_session=False)
        db.query(Registro).filter(Registro.fonte == "camara", Registro.tipo == "tramitacao",
                                  Registro.titulo.in_(["PL 1/2024", "PL 2/2024", "PL 3/2024"])).delete(synchronize_session=False)
        db.query(Proposicao).filter(Proposicao.id_externo.like("p99%")).delete(synchronize_session=False)
        db.query(Parlamentar).filter(Parlamentar.id_externo.in_(IDS)).delete(synchronize_session=False)
        db.commit()


@pytest.fixture
def dados():
    criar_tabelas()
    busca._INDICES.clear()
    _limpar()
    with SessionLocal() as db:
        nik = Parlamentar(casa="camara", id_externo="9901", nome="Nikolas Ferreira", partido="ZZT", uf="MG", em_exercicio=True)
        mar = Parlamentar(casa="camara", id_externo="9902", nome="Maria da Silva", partido="ZZT", uf="SP", em_exercicio=True)
        sen = Parlamentar(casa="senado", id_externo="9903", nome="Pedro de Roraima", partido="ZZS", uf="RR", em_exercicio=True)
        db.add_all([nik, mar, sen])
        db.flush()
        # candidaturas, patrimônio e campanha
        for ano, partido, instrucao, ocupacao, pat, rec in ((2018, "PSL", "Superior incompleto", "Empresário", 100000.0, 50000.0),
                                                             (2022, "PL", "Superior completo", "Deputado", 300000.0, 200000.0)):
            sq = f"9901{ano % 100:03d}"
            r = Registro(fonte="tse", tipo="candidato", chave=f"9901-{ano}", dados={})
            db.add(r)
            db.flush()
            db.add(Candidato(registro_id=r.id, ano=ano, sq_candidato=sq, nome="NIKOLAS FERREIRA", nome_urna="NIKOLAS FERREIRA", partido=partido, uf="MG",
                             cargo="Deputado Federal", situacao_candidatura="Deferido", resultado="Eleito por QP", ocupacao=ocupacao,
                             instrucao=instrucao, parlamentar_id=nik.id))
            db.add(CandidatoFinancas(ano=ano, sq_candidato=sq, uf="MG", patrimonio=pat, receitas=rec, receitas_por_fonte={"Fundo Eleitoral": rec * 0.75, "Partido": rec * 0.25},
                                     despesas=rec * 0.9, despesas_por_tipo={"Publicidade": rec * 0.6, "Pessoal": rec * 0.3}))
        # cota
        for p, tipo, v in ((nik, "PASSAGEM AÉREA - RPA", 1000.0), (nik, "HOSPEDAGEM", 500.0), (nik, "DIVULGAÇÃO DA ATIVIDADE PARLAMENTAR", 2000.0),
                           (mar, "PASSAGEM AÉREA - RPA", 300.0)):
            db.add(Despesa(parlamentar_id=p.id, id_externo=f"d99-{p.id}-{tipo[:4]}", ano=2099, mes=12, tipo=tipo, valor=v))   # ano que nenhum outro teste usa
        # votações nominais
        hoje = date.today()
        votacoes = [Votacao(casa="camara", id_externo=f"v99{i}", data=hoje - timedelta(days=10 + i), secreta=False) for i in range(4)]
        db.add_all(votacoes)
        db.flush()
        for v, voto in zip(votacoes, ("Sim", "Sim", "Sim", "Não")):
            db.add(Voto(votacao_id=v.id, parlamentar_id=nik.id, voto=voto))
        db.add(Voto(votacao_id=votacoes[0].id, parlamentar_id=mar.id, voto="Sim"))
        # projetos de autoria (tramitação coletada)
        for i, (sit, ementa) in enumerate((("Transformado em Norma Jurídica", "Dispõe sobre a saúde pública"), ("Arquivada", "Altera regras de trânsito"),
                                           ("Aguardando Designação de Relator", "Cria programa de saúde mental"))):
            pr = Proposicao(casa="camara", id_externo=f"p99{i}", sigla_tipo="PL", numero=str(i + 1), ano=2024, ementa=ementa, situacao=sit)
            db.add(pr)
            db.flush()
            db.add(Registro(fonte="camara", tipo="tramitacao", chave=str(pr.id), titulo=f"PL {i + 1}/2024",
                            dados={"autores": [{"id_externo": "9901", "casa": "camara"}], "ementa": ementa}))
        # emendas
        db.add(Registro(fonte="transparencia", tipo="emendas_ano", chave="emendas-2023", ano=2023,
                        dados={"autores": {"NIKOLAS FERREIRA": {"empenhado": 1000000.0, "pago": 400000.0}, "OUTRA PESSOA": {"empenhado": 5.0, "pago": 1.0}}}))
        db.commit()
    yield
    _limpar()
    busca._INDICES.clear()


def _ask(p):
    with SessionLocal() as db:
        return ia_propria.responder(db, p)


def test_lista_de_quem_representa_o_estado(dados):
    r = _ask("Quais senadores representam Roraima?")
    assert r["intencao"] == "lista_estado" and r["dados"]["senado"] == ["Pedro de Roraima"]
    assert "Nikolas Ferreira" in _ask("Quais deputados são de MG?")["resposta"]
    pede = _ask("Quais políticos representam cada estado no Senado e na Câmara dos Deputados?")
    assert pede["intencao"] == "lista_estado" and "De qual estado" in pede["resposta"]


def test_historico_partidos_e_formacao_com_nome_errado(dados):
    r = _ask("Qual é o histórico político de Nicolas Ferrera?")
    assert r["intencao"] == "historico_pessoa" and r["resposta"].startswith("Entendi que você se refere a Nikolas Ferreira.")
    assert "2018" in r["resposta"] and "PSL → PL" in r["resposta"] and "Superior completo" in r["resposta"] and "Deputado" in r["resposta"]
    assert r["dados"]["partidos"] == ["PSL", "PL"] and "só o que passou por eleição" in r["aviso"].lower()


def test_patrimonio_e_evolucao(dados):
    r = _ask("Qual foi a evolução do patrimônio declarado do Nikolas Ferreira entre as eleições?")
    assert r["intencao"] == "patrimonio_pessoa"
    assert "R$ 100.000,00" in r["resposta"] and "R$ 300.000,00" in r["resposta"] and "+R$ 200.000,00 (+200%)" in r["resposta"]
    assert "inflação" in r["aviso"]


def test_campanha_origem_das_receitas_sem_nome_de_doador(dados):
    r = _ask("Quanto o Nikolas Ferreira recebeu em doações eleitorais e quais foram seus doadores?")
    assert r["intencao"] == "financas_campanha" and "Campanha de 2022" in r["resposta"] and "Fundo Eleitoral" in r["resposta"]
    assert "CPF não é guardado" in r["aviso"]


def test_projetos_com_cobertura_e_situacao(dados):
    r = _ask("Quantos projetos de lei o Nikolas Ferreira apresentou?")
    assert r["intencao"] == "projetos_pessoa"
    d = r["dados"]
    assert (d["projetos"], d["lei"], d["arquivados"], d["em_andamento"]) == (3, 1, 1, 1)
    assert "Saúde" in r["resposta"] and "NÃO quer dizer" in r["aviso"]


def test_votos_a_favor_contra_e_abstencao(dados):
    r = _ask("Quantas vezes o Nikolas Ferreira votou a favor, contra ou se absteve?")
    assert r["intencao"] == "participacao_pessoa" and r["dados"]["votos"] == {"favor": 3, "contra": 1, "abstencao": 0, "outros": 0}
    assert "licença" in r["aviso"]


def test_ranking_de_participacao_maior_e_menor(dados):
    maior = _ask("Quais parlamentares do ZZT possuem maior participação em votações nominais?")
    menor = _ask("Quais parlamentares do ZZT possuem menor participação em votações nominais?")
    assert maior["dados"]["ranking"][0] == {"nome": "Nikolas Ferreira", "votou": 4}
    assert menor["dados"]["ranking"][0]["nome"] == "Maria da Silva" and "não aparece" in menor["aviso"]


def test_votos_por_tema_avisa_que_nao_separa(dados):
    r = _ask("Como o Nikolas Ferreira votou em projetos relacionados à saúde e educação?")
    assert r["intencao"] == "participacao_pessoa" and r["resposta"].startswith("Ainda não separo os votos por tema")


def test_despesas_por_categoria_viagens_e_geral(dados):
    r = _ask("Quais foram as principais despesas do Nikolas Ferreira com viagens, hospedagens e passagens?")
    assert r["intencao"] == "despesas_categoria" and "PASSAGEM" in r["resposta"] and "HOSPEDAGEM" in r["resposta"] and "DIVULGA" not in r["resposta"]
    geral = _ask("Quais políticos possuem registros de despesas parlamentares e quais são os valores por categoria?")
    assert geral["intencao"] == "despesas_categoria" and "DIVULGA" in geral["resposta"]


def test_condenacoes_so_dos_casos_curados_e_sem_confundir_com_processo(dados):
    r = _ask("Quais políticos possuem condenações definitivas, distinguindo-as de investigações e processos ainda sem decisão final?")
    assert r["intencao"] == "condenacoes_lista" and r["dados"]["total"] == escandalos.crimes()["total"]
    assert "NÃO é o total" in r["aviso"] and "cabe recurso" in r["resposta"].lower() + r["aviso"].lower()


def test_emendas_com_o_corte_dos_maiores_autores(dados):
    r = _ask("Quanto das emendas do Nikolas Ferreira foi empenhado e pago?")
    assert r["intencao"] == "emendas_pessoa" and "R$ 1.000.000,00" in r["resposta"] and "R$ 400.000,00" in r["resposta"]
    assert "30 maiores autores" in r["aviso"] and "liquidado" in r["aviso"]


def test_comparacao_com_a_mesma_casa(dados):
    r = _ask("Como o Nikolas Ferreira se compara com os outros deputados?")
    assert r["intencao"] == "comparar_pessoa" and r["dados"]["gasto"]["posicao"] == 1 and "mesma casa" in r["resposta"]


@pytest.mark.parametrize("pergunta,topico", [
    ("Como votaram individualmente os ministros do STF, STJ e TSE em determinada decisão?", "votos_ministros"),
    ("Quem são os políticos que atualmente ocupam os principais cargos do governo federal?", "governo"),
    ("Quanto o Nikolas Ferreira recebeu de remuneração durante o mandato?", "remuneracao"),
    ("Em quais tribunais existem processos associados ao Nikolas Ferreira?", "tribunais"),
    ("Quanto tempo os processos envolvendo o Nikolas Ferreira estão em tramitação?", "tempo_processo"),
    ("Quais projetos do Nikolas Ferreira tiveram impacto financeiro previsto no orçamento público?", "impacto"),
    ("Quais empresas receberam recursos públicos relacionados a contratos ou emendas indicadas pelo Nikolas Ferreira?", "empresas_emendas")])
def test_quando_nao_ha_dado_diz_que_nao_ha_e_nao_inventa(dados, pergunta, topico):
    r = _ask(pergunta)
    assert r["intencao"] == f"sem_dado:{topico}" and r["entendeu"] and not r["dados"]
    assert "não" in r["resposta"].lower() and "inventar" in r["aviso"]


def test_investigacao_em_orgaos_vai_para_os_casos_curados_e_nao_para_sem_tribunal(dados):
    assert _ask("Existem investigações envolvendo o Nikolas Ferreira em tribunais ou órgãos de controle?")["intencao"] == "processos_pessoa"


def test_nome_citado_e_nao_achado_nao_vira_resposta_geral(dados):
    assert not _ask("Quais condenações tem o Zyxwv Qwrtp?")["entendeu"]
    assert not _ask("Quais processos tem o Zyxwv Qwrtp?")["entendeu"]


# ---------- a tabela de cobertura, pergunta por pergunta ----------

def test_cobertura_tem_as_50_perguntas_e_campos_validos():
    assert [x["n"] for x in COBERTURA] == list(range(1, 51))
    for x in COBERTURA:
        assert x["dado"] in ("completo", "parcial", "nenhum") and x["motor"] in ("pronto", "a_fazer") and x["limite"] and x["pergunta"]
        assert (x["intencao"] is not None) == (x["motor"] == "pronto"), x["n"]


@pytest.mark.parametrize("linha", [x for x in COBERTURA if x["motor"] == "pronto"], ids=lambda x: f"Q{x['n']}")
def test_cada_pergunta_pronta_e_entendida_como_a_tabela_diz(dados, linha):
    pergunta = linha["pergunta"].replace("[nome]", "Nikolas Ferreira").replace("[Nome]", "Nikolas Ferreira")
    r = _ask(pergunta)
    assert r["entendeu"] and r["intencao"] == linha["intencao"], (linha["n"], pergunta, r["intencao"], r["resposta"][:100])


def test_rota_de_cobertura(dados):
    r = TestClient(app).get("/ia/cobertura").json()
    assert r["total"] == 50 and sum(r["dado"].values()) == 50 and sum(r["motor"].values()) == 50 and "Nunca inventar" in r["regra"]
