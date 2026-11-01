"""O que está sendo votado: a ementa da proposição ligada à votação (pelo vínculo ou pelo nome da matéria); sem ligação segura, nada."""
from datetime import date

from app.db import SessionLocal, criar_tabelas
from app.models import Proposicao, Votacao
from app.routers.legislativo import _proposicao_da_votacao


def test_liga_pelo_nome_da_materia_e_nao_chuta():
    criar_tabelas()
    db = SessionLocal()
    try:
        p = Proposicao(casa="camara", id_externo="teste-plp-281", sigla_tipo="PLP", numero="281", ano=2019,
                       ementa="Altera o Código Tributário Nacional.", situacao="Rejeitada")
        db.add(p)
        db.flush()
        v = Votacao(casa="camara", id_externo="teste-v-plp-281", data=date.today(), materia="PLP 281/2019")
        db.add(v)
        db.flush()
        r = _proposicao_da_votacao(db, v)
        assert r["ementa"] == "Altera o Código Tributário Nacional." and r["sigla"] == "PLP"
        semliga = Votacao(casa="camara", id_externo="teste-v-sem", data=date.today(), materia="PL 9999/2030")
        db.add(semliga)
        db.flush()
        assert _proposicao_da_votacao(db, semliga) is None
        assert _proposicao_da_votacao(db, Votacao(casa="camara", id_externo="x", data=date.today(), materia=None)) is None
    finally:
        db.rollback()
        db.close()
