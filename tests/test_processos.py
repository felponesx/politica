"""Processos do parlamentar: representações da Câmara, registro de candidatura e casos curados, sem ligar homônimos."""
import os
import uuid

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import processos  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Candidato, Parlamentar, Proposicao, Registro  # noqa: E402

cliente = TestClient(app)


def _dep(db, nome, casa="camara"):
    p = Parlamentar(casa=casa, id_externo=uuid.uuid4().hex[:10], nome=nome, partido="XX", uf="SP", em_exercicio=True)
    db.add(p)
    db.flush()
    return p


def _cand(db, p, nome_completo, situacao="Deferido", ano=2022):
    r = Registro(fonte="tse", tipo="candidato", chave=uuid.uuid4().hex, dados={})
    db.add(r)
    db.flush()
    db.add(Candidato(registro_id=r.id, ano=ano, sq_candidato=uuid.uuid4().hex[:11], nome=nome_completo, nome_urna=p.nome, uf="SP",
                     cargo="DEPUTADO FEDERAL", situacao_candidatura=situacao, resultado="ELEITO", parlamentar_id=p.id))


def test_nome_na_representacao():
    e = "Representação de autoria do Partido Liberal (PL) em desfavor do Senhor Deputado GLAUBER BRAGA, protocolizada em 6/12/2023. Alegação de quebra de decoro parlamentar."
    assert processos.nome_na_representacao(e) == "glauber braga"
    assert processos.nome_na_representacao("em desfavor da Senhora Deputada FERNANDA MELCHIONNA, protocolizada em 14/12/2023.") == "fernanda melchionna"
    # formatos reais da Câmara em 2025 (conferidos na API)
    assert processos.nome_na_representacao("Representa em desfavor da Senhora Deputada CARLA ZAMBELLI, em razão de condenação criminal transitada em julgado.") == "carla zambelli"
    assert processos.nome_na_representacao("Representação em desfavor do Senhor Deputado Gilvan da Federal, por procedimento incompatível com o decoro parlamentar.") == "gilvan da federal"
    assert processos.nome_na_representacao("Projeto de lei sobre educação") is None


def test_representacao_liga_pelo_nome_parlamentar_unico():
    db = SessionLocal()
    nome = "Zeferino Xavante" + uuid.uuid4().hex[:4]
    p = _dep(db, nome)
    db.add(Proposicao(casa="camara", id_externo=uuid.uuid4().hex[:8], sigla_tipo="REP", numero="9", ano=2024,
                      ementa=f"Representação em desfavor do Senhor Deputado {nome.upper()}, protocolizada em 1/1/2024. Alegação de quebra de decoro parlamentar."))
    db.commit()
    r = cliente.get(f"/parlamentares/{p.id}/processos").json()
    assert [x["titulo"] for x in r["representacoes_decoro"]] == ["REP 9/2024"]
    assert r["representacoes_decoro"][0]["fonte"].startswith("https://www.camara.leg.br/") and "não é condenação" in r["aviso"]
    assert r["stf"]["disponivel"] is False
    # homônimo: dois deputados com o mesmo nome parlamentar -> não liga a nenhum
    outro = _dep(db, nome)
    db.commit()
    assert cliente.get(f"/parlamentares/{p.id}/processos").json()["representacoes_decoro"] == []
    assert cliente.get(f"/parlamentares/{outro.id}/processos").json()["representacoes_decoro"] == []
    db.close()


def test_registro_de_candidatura_nao_deferido():
    db = SessionLocal()
    p = _dep(db, "Fulano Registro" + uuid.uuid4().hex[:4])
    _cand(db, p, "Fulano de Tal Registro", "Deferido", 2022)
    _cand(db, p, "Fulano de Tal Registro", "Indeferido com recurso", 2018)
    db.commit()
    r = cliente.get(f"/parlamentares/{p.id}/processos").json()
    assert [(x["ano"], x["situacao"]) for x in r["registro_de_candidatura"]] == [(2018, "Indeferido com recurso")]
    db.close()


def test_caso_curado_so_com_nome_completo_igual():
    db = SessionLocal()
    p = _dep(db, "Dirceu Teste" + uuid.uuid4().hex[:4])
    _cand(db, p, "José Dirceu de Oliveira e Silva")  # nome completo diferente do curado ("José Dirceu"): não liga
    q = _dep(db, "Outro Nome" + uuid.uuid4().hex[:4])
    _cand(db, q, "José Dirceu")  # igual ao nome curado
    db.commit()
    assert cliente.get(f"/parlamentares/{p.id}/processos").json()["casos_curados"] == []
    r = cliente.get(f"/parlamentares/{q.id}/processos").json()["casos_curados"]
    assert "mensalao" in [x["slug"] for x in r] and all(x["fonte"].startswith("http") and "nome completo" in x["ligacao"] for x in r)
    # outra pessoa com o mesmo nome completo na base (homônimo): ninguém é ligado
    z = _dep(db, "Terceiro Nome" + uuid.uuid4().hex[:4])
    _cand(db, z, "José Dirceu")
    db.commit()
    assert cliente.get(f"/parlamentares/{q.id}/processos").json()["casos_curados"] == []
    db.close()


def test_processos_404_e_senador_sem_representacao():
    assert cliente.get("/parlamentares/99999999/processos").status_code == 404
    db = SessionLocal()
    s = _dep(db, "Senador Teste" + uuid.uuid4().hex[:4], casa="senado")
    db.commit()
    r = cliente.get(f"/parlamentares/{s.id}/processos").json()
    assert r["representacoes_decoro"] == [] and r["casos_curados"] == [] and r["registro_de_candidatura"] == []
    db.close()
