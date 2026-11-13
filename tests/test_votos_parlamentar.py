"""Votações do parlamentar: o padrão são 20 votos e a quantidade pedida vai de 1 a 100."""
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.db import SessionLocal, criar_tabelas
from app.main import app
from app.models import Parlamentar, Votacao, Voto

cli = TestClient(app)


def _parlamentar_com_votos(n):
    db = SessionLocal()
    try:
        p = Parlamentar(casa="camara", id_externo=f"votos-{n}-{date.today().isoformat()}-{id(db)}", nome="Teste Votos", partido="AAA", uf="SP", em_exercicio=True)
        db.add(p)
        db.flush()
        for i in range(n):
            v = Votacao(casa="camara", id_externo=f"vt-{p.id}-{i}", data=date.today() - timedelta(days=i), materia=f"PL {i}/2026")
            db.add(v)
            db.flush()
            db.add(Voto(votacao_id=v.id, parlamentar_id=p.id, voto="Sim", partido_na_data="AAA"))
        db.commit()
        return p.id
    finally:
        db.close()


def test_padrao_20_e_quantidade_pedida():
    criar_tabelas()
    pid = _parlamentar_com_votos(25)
    assert len(cli.get(f"/parlamentares/{pid}").json()["ultimos_votos"]) == 20
    assert len(cli.get(f"/parlamentares/{pid}?votos=25").json()["ultimos_votos"]) == 25
    assert len(cli.get(f"/parlamentares/{pid}?votos=100").json()["ultimos_votos"]) == 25  # só há 25 no banco


def test_quantidade_fora_da_faixa_e_recusada():
    criar_tabelas()
    pid = _parlamentar_com_votos(3)
    assert cli.get(f"/parlamentares/{pid}?votos=0").status_code == 422
    assert cli.get(f"/parlamentares/{pid}?votos=101").status_code == 422
