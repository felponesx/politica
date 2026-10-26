"""Lista de projetos com autor, relator, placar e fase."""
import os
import uuid
from datetime import date

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

from fastapi.testclient import TestClient  # noqa: E402

from app import projetos  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Parlamentar, Proposicao, Registro, Votacao, Voto  # noqa: E402

cliente = TestClient(app)
ANO = 3000 + uuid.uuid4().int % 6000  # ano só deste teste: a base de testes guarda o que os testes gravam


def _prop(db, numero, situacao=None, tipo="PL", casa="camara", ano=ANO):
    p = Proposicao(casa=casa, id_externo=uuid.uuid4().hex[:9], sigla_tipo=tipo, numero=str(numero), ano=ano, ementa=f"Dispõe sobre o tema {numero}.",
                   situacao=situacao, data_apresentacao=date(2987, 2, 10))
    db.add(p)
    db.flush()
    return p


def test_relator_do_texto_da_tramitacao():
    assert projetos._relator([{"descricao": "Designado Relator, Dep. Fulano de Tal (PT-SP)", "despacho": ""}]) == "Fulano de Tal"
    assert projetos._relator([{"descricao": "Recebimento", "despacho": ""}]) is None
    assert projetos._relator([{"descricao": "Parecer do Relator", "despacho": "Aprovado"}]) is None  # não é designação


def test_fases_placar_e_autor():
    db = SessionLocal()
    dep = Parlamentar(casa="camara", id_externo="77" + uuid.uuid4().hex[:5], nome="Autora Teste", partido="XX", uf="SP", em_exercicio=True)
    db.add(dep)
    db.flush()
    votado = _prop(db, 9001, "Aguardando Sanção")
    v = Votacao(casa="camara", id_externo=uuid.uuid4().hex[:9], data=date(2987, 3, 1), resultado="Aprovada", proposicao_id=votado.id,
                placar_oficial={"sim": 37, "nao": 7, "abstencao": 6})
    db.add(v)
    db.add(Registro(fonte="camara", tipo="tramitacao", chave=str(votado.id),
                    dados={"autores": [{"nome": "Autora Teste", "tipo": "Deputado", "id_externo": dep.id_externo, "casa": "camara"}, {"nome": "Outro"}],
                           "passos": [{"descricao": "Designado Relator, Dep. Beltrano Silva (XX-SP)", "despacho": ""}]}))
    nominal = _prop(db, 9002)
    vn = Votacao(casa="camara", id_externo=uuid.uuid4().hex[:9], data=date(2987, 3, 2), resultado="Rejeitada", proposicao_id=nominal.id)
    db.add(vn)
    db.flush()
    for i, t in enumerate(["Sim", "Sim", "Não", "Abstenção"]):
        d2 = Parlamentar(casa="camara", id_externo=f"v{i}{uuid.uuid4().hex[:6]}", nome=f"Votante {i}{uuid.uuid4().hex[:3]}", em_exercicio=True)
        db.add(d2)
        db.flush()
        db.add(Voto(votacao_id=vn.id, parlamentar_id=d2.id, voto=t))
    pronto = _prop(db, 9003, "Pronta para Pauta no Plenário")
    parado = _prop(db, 9004, "Aguardando Designação de Relator")
    # sessão em andamento hoje com o projeto na pauta
    em_vot = _prop(db, 9005, "Aguardando Parecer")
    db.add(Registro(fonte="camara", tipo="evento", chave=uuid.uuid4().hex[:8],
                    dados={"dia": date.today().isoformat(), "situacao": "Em Andamento", "pauta": [{"proposicao": f"PL 9005/{em_vot.ano} - Dispõe sobre", "titulo": None}]}))
    db.commit()
    ids = {x: p.id for x, p in (("votado", votado), ("nominal", nominal), ("pronto", pronto), ("parado", parado), ("em_vot", em_vot))}
    r = cliente.get("/proposicoes", params={"ano": ANO, "limit": 50}).json()["itens"]
    por = {i["id"]: i for i in r}
    a = por[ids["votado"]]
    assert a["fase"] == "votado" and a["placar"]["sim"] == 37 and a["placar"]["nao"] == 7 and a["placar"]["abstencao"] == 6 and a["placar"]["resultado"] == "Aprovada"
    assert a["autor"]["nome"] == "Autora Teste" and a["autor"]["partido"] == "XX" and a["autor"]["outros"] == 1 and a["relator"] == "Beltrano Silva"
    n = por[ids["nominal"]]["placar"]  # sem placar oficial: conta os votos nominais
    assert (n["sim"], n["nao"], n["abstencao"]) == (2, 1, 1) and n["resultado"] == "Rejeitada"
    assert por[ids["pronto"]]["fase"] == "a_votar" and por[ids["parado"]]["fase"] is None and por[ids["em_vot"]]["fase"] == "em_votacao"
    assert por[ids["parado"]]["autor"] is None and por[ids["parado"]]["placar"] is None  # nada inventado
    for fase, esperado in (("votado", {"votado", "nominal"}), ("a_votar", {"pronto"}), ("em_votacao", {"em_vot"})):
        got = {i["id"] for i in cliente.get("/proposicoes", params={"ano": ANO, "fase": fase, "limit": 50}).json()["itens"]}
        assert got == {ids[x] for x in esperado}, fase
    assert cliente.get("/proposicoes", params={"fase": "xx"}).status_code == 422
    assert cliente.get("/proposicoes", params={"q": "%%", "ano": ANO}).json()["total"] == 0  # curinga não casa tudo
    db.close()


def test_representacao_e_requerimento_nao_entram_na_lista_de_projetos():
    db = SessionLocal()
    r = _prop(db, 9100, tipo="REP")
    rq = _prop(db, 9101, tipo="REQ")
    db.commit()
    ids = [i["id"] for i in cliente.get("/proposicoes", params={"ano": ANO, "limit": 100}).json()["itens"]]
    assert r.id not in ids and rq.id not in ids
    assert r.id in [i["id"] for i in cliente.get("/proposicoes", params={"ano": ANO, "tipo": "REP", "limit": 100}).json()["itens"]]
    db.close()


def test_busca_por_numero():
    db = SessionLocal()
    p = _prop(db, 77123)
    db.commit()
    assert p.id in [i["id"] for i in cliente.get("/proposicoes", params={"q": "77123", "ano": ANO}).json()["itens"]]
    db.close()


def test_filtro_desde_a_data():
    db = SessionLocal()
    p = _prop(db, 77124)
    db.commit()
    ids = lambda d: [i["id"] for i in cliente.get("/proposicoes", params={"ano": ANO, "desde": d}).json()["itens"]]  # noqa: E731
    assert p.id in ids("2987-02-10") and p.id not in ids("2987-02-11")
    db.close()
