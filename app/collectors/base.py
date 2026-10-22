import logging
from contextlib import contextmanager
from datetime import datetime

from app.db import SessionLocal
from app.models import Coleta, Parlamentar

log = logging.getLogger("brasilplus.coleta")


class Contador:
    def __init__(self):
        self.itens = 0
        self.avisos: list[str] = []  # falhas parciais: a coleta termina como "parcial" e o texto vai para o erro

    def __iadd__(self, n):
        self.itens += n
        return self


@contextmanager
def registrar_coleta(fonte: str, tarefa: str, **parametros):
    """Abre sessão, registra a execução em `coletas` e grava status/erro ao final."""
    db = SessionLocal()
    coleta = Coleta(fonte=fonte, tarefa=tarefa, parametros={k: str(v) for k, v in parametros.items()})
    db.add(coleta)
    db.commit()
    cont = Contador()
    log.info("Iniciando %s.%s %s", fonte, tarefa, parametros)
    try:
        yield db, cont
        db.commit()
        coleta.status = "parcial" if cont.avisos else "ok"
        if cont.avisos:
            coleta.erro = "; ".join(cont.avisos)[:4000]
    except Exception as e:
        db.rollback()
        coleta.status = "erro"
        coleta.erro = f"{type(e).__name__}: {e}"[:4000]
        log.exception("Erro em %s.%s", fonte, tarefa)
        raise
    finally:
        coleta.itens = cont.itens
        coleta.fim = datetime.now()
        db.add(coleta)
        db.commit()
        db.close()
        log.info("Fim %s.%s: %s itens (%s)", fonte, tarefa, cont.itens, coleta.status)


def marcar_em_exercicio(db, casa: str, ids_atuais: set[str], minimo: int) -> int:
    """Quem não está mais na lista atual da casa (titular que voltou, suplente que saiu) deixa de constar como em exercício.
    Só mexe quando a lista veio com pelo menos `minimo` nomes: uma resposta cortada não pode apagar a casa inteira."""
    if len(ids_atuais) < minimo:
        log.warning("Lista atual de %s veio com %s nomes (mínimo %s): em_exercicio não foi atualizado", casa, len(ids_atuais), minimo)
        return 0
    saidas = db.query(Parlamentar).filter(Parlamentar.casa == casa, Parlamentar.em_exercicio.is_(True),
                                          Parlamentar.id_externo.notin_(ids_atuais)).all()
    for p in saidas:
        p.em_exercicio = False
    db.flush()
    return len(saidas)
