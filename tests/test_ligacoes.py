import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./teste.db")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import SessionLocal, criar_tabelas  # noqa: E402
from app.ligacoes import ligar_tudo  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (Candidato, Contrato, Despesa, Norma, Parlamentar, Proposicao, Registro,  # noqa: E402
                        ResultadoEleicao, Votacao)

criar_tabelas()
cliente = TestClient(app)


def _registro(db, chave):
    r = Registro(fonte="teste", tipo="teste", chave=chave, dados={})
    db.add(r)
    db.flush()
    return r.id


def test_ligacoes():
    db = SessionLocal()
    dep = Parlamentar(casa="camara", id_externo="L1", nome="Joana Ligação", partido="ABC", uf="PE")
    homonimo = Parlamentar(casa="camara", id_externo="L2", nome="José Repetido", partido="XYZ", uf="PE")
    prop = Proposicao(casa="camara", id_externo="LP1", sigla_tipo="PLP", numero="7744", ano=2031, ementa="Teste")
    db.add_all([dep, homonimo, prop])
    db.flush()
    db.add_all([
        Votacao(casa="camara", id_externo="LV1", materia="PLP 7744/2031", resultado="Aprovada"),
        Norma(tipo="LCP", id_externo="LN1", numero="999", ano=2031, proposicao_id=prop.id),
        Candidato(registro_id=_registro(db, "c1"), ano=2030, sq_candidato="LSQ1", nome="JOANA DA SILVA",
                  nome_urna="JOANA LIGAÇÃO", partido="ABC", uf="PE", cargo="DEPUTADO FEDERAL"),
        # dois candidatos com o mesmo nome de urna no mesmo ano -> não liga
        Candidato(registro_id=_registro(db, "c2"), ano=2030, sq_candidato="LSQ2", nome_urna="JOSE REPETIDO",
                  uf="PE", cargo="DEPUTADO FEDERAL"),
        Candidato(registro_id=_registro(db, "c3"), ano=2030, sq_candidato="LSQ3", nome_urna="JOSÉ REPETIDO",
                  uf="PE", cargo="DEPUTADO FEDERAL"),
        ResultadoEleicao(ano=2030, turno=1, uf="PE", cargo="DEPUTADO FEDERAL", sq_candidato="LSQ1",
                         nome="JOANA LIGAÇÃO", votos=150000, eleito=True),
        Despesa(parlamentar_id=dep.id, id_externo="LD1", ano=2031, valor=5000.0, fornecedor="GRAFICA LIGADA",
                cnpj_cpf="11222333000181"),
        Contrato(registro_id=_registro(db, "k1"), fonte="pncp", numero_controle="LK1", esfera="M", uf="PE",
                 fornecedor="GRAFICA LIGADA LTDA", cnpj_fornecedor="11222333000181", objeto="Impressos", valor=90000.0),
    ])
    db.commit()
    db.close()

    r = ligar_tudo()
    assert r["votacoes_proposicoes"] >= 1 and r["parlamentares_candidaturas"] >= 1

    pid = cliente.get("/parlamentares", params={"q": "Joana Liga"}).json()["itens"][0]["id"]
    lig = cliente.get(f"/parlamentares/{pid}/ligacoes").json()
    assert lig["candidaturas"][0]["votos"] == 150000
    assert lig["fornecedores_com_contratos_publicos"][0]["valor_contratos_publicos"] == 90000.0
    assert lig["aviso"]

    hid = cliente.get("/parlamentares", params={"q": "Repetido"}).json()["itens"][0]["id"]
    assert cliente.get(f"/parlamentares/{hid}/ligacoes").json()["candidaturas"] == []

    f = cliente.get("/fornecedores/11.222.333/0001-81").json()
    assert f["aparece_nas_duas_bases"] and f["cota_parlamentar"]["parlamentares"][0]["nome"] == "Joana Ligação"
    assert f["documento"] == "11.222.333/0001-81"
    cruz = cliente.get("/fornecedores-cruzados").json()["itens"]
    assert any(c["cnpj"] == "11222333000181" for c in cruz)

    prop_id = cliente.get("/proposicoes", params={"q": "Teste", "ano": 2031}).json()["itens"][0]["id"]
    det = cliente.get(f"/proposicoes/{prop_id}").json()
    assert det["votacoes"][0]["resultado"] == "Aprovada" and det["norma_gerada"]["numero"] == "999"

    cid = cliente.get("/contratos", params={"uf": "PE"}).json()["itens"][0]["id"]
    assert cliente.get(f"/contratos/{cid}").json()["fornecedor"]["tambem_na_cota_parlamentar"]["total"] == 5000.0
