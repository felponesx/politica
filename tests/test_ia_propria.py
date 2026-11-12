"""IA própria do BRASIL+: perguntas em português respondidas pelo banco, sem modelo de linguagem e sem custo."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import busca, ia_propria
from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import Despesa, Parlamentar, Registro

IDS = ["9701", "9702", "9703", "9704"]


@pytest.fixture
def dados():
    criar_tabelas()
    busca._INDICES.clear()
    _limpar()
    with SessionLocal() as db:
        nik = Parlamentar(casa="camara", id_externo="9701", nome="Nikolas Ferreira", partido="PL", uf="MG", em_exercicio=True)
        mar = Parlamentar(casa="camara", id_externo="9702", nome="Maria da Silva", partido="PT", uf="SP", em_exercicio=True)
        joa = Parlamentar(casa="senado", id_externo="9703", nome="João Paulo Teste", partido="PT", uf="BA", em_exercicio=True)
        ant = Parlamentar(casa="camara", id_externo="9704", nome="Antônio Velho", partido="PT", uf="SP", em_exercicio=False)
        db.add_all([nik, mar, joa, ant])
        db.flush()
        for i, (p, ano, mes, v) in enumerate([(nik, 2024, 1, 1000.50), (nik, 2024, 12, 2500.00), (nik, 2023, 5, 4000.00),
                                              (mar, 2024, 6, 9000.00), (joa, 2024, 3, 500.00)]):
            db.add(Despesa(parlamentar_id=p.id, id_externo=f"d97{i}", ano=ano, mes=mes, valor=v))
        db.commit()
    yield
    _limpar()
    busca._INDICES.clear()


def _limpar():
    with SessionLocal() as db:
        ids = db.scalars(select(Parlamentar.id).where(Parlamentar.id_externo.in_(IDS))).all()
        if ids:
            db.query(Despesa).filter(Despesa.parlamentar_id.in_(ids)).delete(synchronize_session=False)
        db.query(Parlamentar).filter(Parlamentar.id_externo.in_(IDS)).delete(synchronize_session=False)
        db.query(Registro).filter(Registro.fonte == "ia").delete(synchronize_session=False)
        db.commit()


def _ask(pergunta):
    with SessionLocal() as db:
        return ia_propria.responder(db, pergunta)


def test_quem_mais_gastou_com_a_cota(dados):
    r = _ask("Quem mais gastou com a cota parlamentar em 2024?")
    assert r["entendeu"] and r["intencao"] == "gasto_ranking"
    assert r["dados"]["ranking"][0]["nome"] == "Maria da Silva" and "R$ 9.000,00" in r["resposta"]
    assert r["aviso"] is None   # as despesas vão até dezembro: o ano está completo
    assert r["fontes"]


def test_quanto_gastou_mesmo_com_o_nome_errado(dados):
    r = _ask("Quanto o Nicolas Ferrera gastou em 2024?")
    assert r["intencao"] == "gasto_pessoa" and "Nikolas Ferreira" in r["resposta"] and "R$ 3.500,50" in r["resposta"]


def test_gasto_sem_ano_mostra_os_anos(dados):
    r = _ask("quanto o nikolas ferreira gastou")
    anos = {x["ano"]: x["total"] for x in r["dados"]["por_ano"]}
    assert anos == {2024: 3500.5, 2023: 4000.0}


def test_quantos_deputados_do_partido(dados):
    with SessionLocal() as db:
        esperado = db.scalar(select(func.count()).select_from(Parlamentar).where(
            Parlamentar.casa == "camara", Parlamentar.partido == "PT", Parlamentar.em_exercicio.is_(True)))
    r = _ask("Quantos deputados do PT tem?")
    assert r["intencao"] == "quantos_parlamentares" and r["dados"]["por_casa"].get("camara", 0) == esperado >= 1   # o fora de exercício não conta
    assert "senadores" not in r["resposta"]
    if esperado == 1:
        assert "1 deputado federal" in r["resposta"] and "1 deputados" not in r["resposta"]


def test_quantos_senadores_de_um_estado_pelo_nome_e_pela_sigla(dados):
    por_nome = _ask("Quantos senadores da Bahia?")
    por_sigla = _ask("Quantos senadores de BA?")
    assert por_nome["dados"]["por_casa"] == por_sigla["dados"]["por_casa"] and por_nome["dados"]["por_casa"].get("senado", 0) >= 1


def test_quem_e_pessoa_escrita_errada(dados):
    r = _ask("Quem é o Nicolas Ferreira?")
    assert r["intencao"] == "perfil" and "Nikolas Ferreira" in r["resposta"] and "PL" in r["resposta"] and "MG" in r["resposta"]


def test_quem_tem_mais_processos_diz_que_nao_ha_base_e_nao_inventa(dados):
    r = _ask("Qual candidato tem mais processos?")
    assert r["entendeu"] and r["intencao"] == "processos_ranking"
    assert "base aberta" in r["resposta"] and r["aviso"] and "não é condenação" in r["aviso"]
    assert not r["dados"]


def test_processos_de_uma_pessoa_sempre_com_o_aviso_de_inocencia(dados):
    r = _ask("Processos do Nikolas Ferreira")
    assert r["intencao"] == "processos_pessoa" and "não é condenação" in r["aviso"]
    assert "base aberta" in r["resposta"]


def test_pergunta_que_nao_entende_diz_isso_e_guarda_para_aprender(dados):
    assert not _ask("qual a cor do céu azul")["entendeu"]
    r = _ask("qual a cor do céu azul")
    assert not r["entendeu"] and r["sugestoes"]
    with SessionLocal() as db:
        guardada = db.scalar(select(Registro).where(Registro.fonte == "ia", Registro.tipo == "pergunta_sem_resposta"))
    assert guardada.dados["vezes"] == 2 and "céu" in guardada.dados["pergunta"]


def test_rota_da_api(dados):
    r = TestClient(app).get("/ia/pergunta", params={"q": "Quantos deputados do PT tem?"})
    assert r.status_code == 200 and r.json()["intencao"] == "quantos_parlamentares"
    assert TestClient(app).get("/ia/pergunta", params={"q": "a"}).status_code == 422


def test_nao_usa_nenhum_servico_de_ia_de_fora():
    """A IA própria não chama Gemini, Claude, GPT nem nada de fora: sem token, sem custo."""
    import pathlib
    codigo = (pathlib.Path(ia_propria.__file__)).read_text(encoding="utf-8")
    for proibido in ("httpx", "requests", "urllib", "anthropic", "openai", "generativelanguage", "gemini"):
        assert proibido not in codigo.lower(), proibido


def test_lista_de_perguntas_sem_resposta_e_o_painel_mostra(dados):
    _ask("qual a cor do céu azul")
    _ask("qual a cor do céu azul")
    _ask("como fazer bolo de cenoura")
    lista = TestClient(app).get("/ia/perguntas-sem-resposta").json()
    assert lista[0]["vezes"] == 2 and "céu" in lista[0]["pergunta"] and len(lista) == 2
    assert "/ia/perguntas-sem-resposta" in TestClient(app).get("/painel").text


def test_nome_com_palavra_a_mais_nao_vira_outra_pessoa(dados):
    """"Nikolas Ferreira Costa" não pode ser respondido como "Nikolas Ferreira": a palavra com inicial maiúscula é parte do nome."""
    r = _ask("Processos do Nikolas Ferreira Costa")
    assert not r["entendeu"]
    assert _ask("Processos do Nikolas Ferreira")["intencao"] == "processos_pessoa"


def test_diz_quem_entendeu_quando_o_nome_nao_e_igual(dados):
    aproximado = _ask("Quanto o Nicolas Ferrera gastou em 2024?")["resposta"]
    exato = _ask("Quanto o Nikolas Ferreira gastou em 2024?")["resposta"]
    assert aproximado.startswith("Entendi que você se refere a Nikolas Ferreira.")
    assert not exato.startswith("Entendi")
    assert _ask("Processos do Nicolas Ferrera")["resposta"].startswith("Entendi que você se refere a Nikolas Ferreira.")


def test_palavras_com_cedilha_sao_reconhecidas(dados):
    """Regressão: a normalização de nomes trocava ç por s, e o motor deixava de reconhecer doações, condenações, votações, ocupação..."""
    from app.ia_propria import _norm_kw
    assert _norm_kw("Doações, condenações e votações — ocupação") == "doacoes condenacoes e votacoes ocupacao"
    assert _ask("Nikolas Ferreira possui condenações?")["intencao"] == "processos_pessoa"


# ---------- quando não sabe, pergunta de volta ----------

def test_sem_dizer_de_quem_pergunta_de_quem_e_oferece_opcoes(dados):
    r = _ask("Quanto gastou em 2024?")
    assert not r["entendeu"] and r["entendi"]["ano"] == 2024 and "gastos da cota parlamentar" in r["entendi"]["assunto"]
    assert "de qual parlamentar" in r["pergunta_de_volta"].lower() and any("de quem" in x for x in r["falta"])
    assert "Quem mais gastou com a cota parlamentar em 2024?" in r["sugestoes"]
    assert "Entendi:" in r["resposta"] and "Faltou:" in r["resposta"] and "/ia/cobertura" in r["resposta"]


def test_nome_que_nao_bate_inteiro_so_sugere_nao_responde(dados):
    r = _ask("Processos do Nikolas Ferreira Costa")
    assert not r["entendeu"] and "Você quis dizer Nikolas Ferreira" in r["pergunta_de_volta"]
    assert "Processos de Nikolas Ferreira" in r["sugestoes"]
    assert "representação" not in r["resposta"].lower() and "caso" not in r["resposta"].lower().replace("caso a", "")   # nenhum fato sobre ninguém
    assert "qual pessoa você quis dizer" in r["falta"]


def test_nome_que_nao_existe_explica_o_que_o_banco_tem(dados):
    r = _ask("Zyxwv Qwrtp")
    assert not r["entendeu"] and "Não encontrei ninguém" in r["pergunta_de_volta"] and "deputado(a) ou senador(a)" in r["pergunta_de_volta"]
    assert r["sugestoes"]


def test_pergunta_sem_nada_reconhecido_pergunta_sobre_quem_ou_o_que(dados):
    r = _ask("qual a cor do céu azul")
    assert not r["entendeu"] and r["pergunta_de_volta"] == "Sobre quem ou sobre o quê você quer saber?" and len(r["sugestoes"]) >= 6
    assert r["entendi"]["assunto"] == [] and len(r["falta"]) == 2


def test_so_o_estado_ou_so_o_partido_pergunta_o_que_quer_saber(dados):
    uf = _ask("Bahia")
    assert uf["entendi"]["estado"] == "BA" and "o que você quer saber" in uf["pergunta_de_volta"] and any("senadores" in x for x in uf["sugestoes"])
    partido = _ask("PL")
    assert partido["entendi"]["partido"] == "PL" and "Quantos deputados do PL tem?" in partido["sugestoes"]


def test_so_o_nome_mostra_quem_e_e_pergunta_o_que_mais(dados):
    r = _ask("Maria da Silva")
    assert r["entendeu"] and r["intencao"] == "perfil" and r["pergunta_de_volta"] == "O que mais você quer saber sobre Maria da Silva?"
    assert "Quanto Maria da Silva gastou com a cota parlamentar?" in r["sugestoes"] and len(r["sugestoes"]) >= 6


def test_pergunta_de_volta_chega_pela_api_e_a_pergunta_continua_guardada(dados):
    r = TestClient(app).get("/ia/pergunta", params={"q": "Quanto gastou em 2024?"}).json()
    assert r["pergunta_de_volta"] and r["falta"] and r["entendi"]["ano"] == 2024
    with SessionLocal() as db:
        assert db.scalar(select(Registro).where(Registro.fonte == "ia", Registro.tipo == "pergunta_sem_resposta")) is not None


def test_exemplos_usam_nomes_reais_do_banco_e_variam(dados):
    from sqlalchemy import select
    with SessionLocal() as db:
        reais = set(db.execute(select(Parlamentar.nome).where(Parlamentar.em_exercicio.is_(True), Parlamentar.partido.is_not(None),
                                                              Parlamentar.uf.is_not(None))).scalars())
    vistos = set()
    for q in ("qual a cor do céu azul", "quanto custa um sapato", "me fale do vento", "isso aí", "xpto abc", "como assim hoje"):
        r = _ask(q)
        achados = {n for n in reais if any(n in s for s in r["sugestoes"])}
        assert len(achados) >= 1, r["sugestoes"]
        vistos |= achados
        assert _ask(q)["sugestoes"] == r["sugestoes"]   # mesma pergunta, mesmos exemplos
    assert "Nikolas Ferreira" not in "".join(_ask("Quanto gastou em 2024?")["sugestoes"]) or "Nikolas Ferreira" in reais
    assert len(vistos) >= 2   # perguntas diferentes mostram pessoas diferentes
