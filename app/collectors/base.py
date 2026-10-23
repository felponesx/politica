import logging
from contextlib import contextmanager
from datetime import datetime

from app.db import SessionLocal, engine
from app.models import Coleta, Parlamentar

log = logging.getLogger("brasilplus.coleta")


class ColetaEmAndamento(RuntimeError):
    """A mesma tarefa, com os mesmos parâmetros, já está rodando (duas coletas iguais ao mesmo tempo duplicariam trabalho e disputariam linhas)."""


def _travar(fonte, tarefa, parametros):
    """Trava de aviso do Postgres por (fonte, tarefa, parâmetros): é solta sozinha se o processo morrer. Devolve a conexão que a segura."""
    if engine.dialect.name != "postgresql":
        return None
    import hashlib
    chave = int.from_bytes(hashlib.sha256(f"{fonte}|{tarefa}|{sorted(parametros.items())}".encode()).digest()[:8], "big", signed=True)
    con = engine.connect()
    try:
        if con.exec_driver_sql("SELECT pg_try_advisory_lock(%s)", (chave,)).scalar():
            return con, chave
    except Exception:
        con.close()
        raise
    con.close()
    return False


def _soltar(trava):
    if trava:
        con, chave = trava
        try:
            con.exec_driver_sql("SELECT pg_advisory_unlock(%s)", (chave,))
        finally:
            con.close()


def _fechar_abortadas(db, horas: int = 12):
    """Coleta que ficou "rodando" há muito tempo (processo morreu) passa a "abortada", para não parecer em andamento para sempre."""
    from datetime import timedelta
    try:
        db.query(Coleta).filter(Coleta.status == "rodando", Coleta.inicio < datetime.now() - timedelta(hours=horas)) \
            .update({"status": "abortada", "fim": datetime.now(), "erro": "processo encerrado antes de terminar"}, synchronize_session=False)
        db.commit()
    except Exception as e:
        log.warning("não consegui fechar coletas abortadas: %s", type(e).__name__)
        db.rollback()


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
    trava = _travar(fonte, tarefa, parametros)  # None = sem trava (SQLite); False = outra coleta igual em andamento
    if trava is False:
        db.close()
        raise ColetaEmAndamento(f"{fonte}.{tarefa} já está rodando em outro processo")
    _fechar_abortadas(db)
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
        _soltar(trava)
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
