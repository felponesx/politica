"""Perguntas em português respondidas pelo próprio BRASIL+ (app/ia_propria.py): sem modelo de linguagem, sem token e sem custo."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ia_propria
from app.db import get_db
from app.models import Registro

router = APIRouter(tags=["IA própria"])


@router.get("/ia/pergunta")
def perguntar(q: str = Query(..., min_length=2, max_length=300, description="A pergunta, em português"), db: Session = Depends(get_db)):
    """Responde com o que está no banco, citando a fonte. Se não entende, diz e sugere perguntas parecidas."""
    return ia_propria.responder(db, q)


@router.get("/ia/perguntas-sem-resposta")
def sem_resposta(db: Session = Depends(get_db)):
    """As perguntas que a IA própria não entendeu, as mais feitas primeiro: cada uma frequente vira um tipo novo de pergunta."""
    linhas = db.scalars(select(Registro).where(Registro.fonte == "ia", Registro.tipo == "pergunta_sem_resposta")
                        .order_by(Registro.valor.desc(), Registro.id.desc()).limit(50)).all()
    return [{"pergunta": r.titulo, "vezes": int(r.valor or 0)} for r in linhas]


@router.get("/ia/cobertura")
def cobertura():
    """As 50 perguntas de treinamento e o que o BRASIL+ consegue responder de cada uma: `dado` (completo, parcial ou nenhum: o que existe nas
    fontes abertas) e `motor` (pronto ou a_fazer: o que a IA própria já responde). Cada linha diz a fonte e o que o dado NÃO cobre."""
    import json
    from pathlib import Path
    itens = json.loads((Path(__file__).resolve().parent.parent / "dados" / "ia_cobertura.json").read_text(encoding="utf-8"))
    cont = lambda k, v: sum(1 for x in itens if x[k] == v)
    return {"total": len(itens), "dado": {k: cont("dado", k) for k in ("completo", "parcial", "nenhum")},
            "motor": {k: cont("motor", k) for k in ("pronto", "a_fazer")}, "perguntas": itens,
            "regra": "Nunca inventar. Investigação, processo e condenação são coisas diferentes. Não ter o registro no banco não prova que algo não existe."}
