"""Alinhamento com a maioria do partido: só Sim/Não, mínimo de colegas, empate sem maioria, secreta fora."""
from datetime import date

from app import fidelidade
from app.db import SessionLocal, criar_tabelas
from app.models import Parlamentar, Votacao, Voto


def _monta(db, votacoes):
    ps = [Parlamentar(casa="camara", id_externo=f"fid{i}", nome=f"Dep {i}", partido="AAA", uf="SP", em_exercicio=True) for i in range(5)]
    db.add_all(ps)
    db.flush()
    for n, (secreta, votos) in enumerate(votacoes):
        v = Votacao(casa="camara", id_externo=f"fidv{n}", data=date.today(), secreta=secreta)
        db.add(v)
        db.flush()
        for p, voto in zip(ps, votos):
            db.add(Voto(votacao_id=v.id, parlamentar_id=p.id, voto=voto, partido_na_data="AAA"))
    db.flush()
    return ps


def test_alinhamento_conta_maioria_e_ignora_secreta_empate_e_abstencao():
    criar_tabelas()
    db = SessionLocal()
    try:
        ps = _monta(db, [(False, ["Sim", "Sim", "Sim", "Sim", "Não"])] * 10 + [(False, ["Sim", "Sim", "Não", "Não", "Sim"][:4] + ["Abstenção"])]
                    + [(True, ["Não"] * 5)])
        r = fidelidade.calcular(db, "camara")
        assert r[ps[0].id]["comparadas"] == 10 and r[ps[0].id]["percentual"] == 100.0  # empate (2x2) e secreta ficaram de fora
        assert r[ps[4].id]["alinhadas"] == 0 and r[ps[4].id]["percentual"] == 0.0
        assert fidelidade.do_parlamentar(db, ps[0])["percentual"] == 100.0
        rk = fidelidade.ranking(db, "camara")
        assert rk["menos_alinhados"][0]["id"] == ps[4].id and "orientação" in rk["nota"]
    finally:
        db.rollback()
        db.close()
