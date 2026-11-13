from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
if settings.database_url.startswith("postgres") and settings.somente_leitura and settings.consulta_timeout_ms > 0:
    # API pública: uma consulta pesada não segura o banco (as coletas, que usam outro processo, não têm esse limite)
    _connect_args["options"] = f"-c statement_timeout={int(settings.consulta_timeout_ms)}"
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=_connect_args)
if engine.dialect.name == "sqlite" and settings.sqlite_wal:
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_con, _registro):
        cur = dbapi_con.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

# Escrita só para o cadastro de fontes (usuário com permissão de escrever, separado do de leitura da API).
_engine_escrita = (create_engine(settings.database_url_escrita, pool_pre_ping=True)
                   if settings.database_url_escrita else None)
SessionEscrita = sessionmaker(bind=_engine_escrita, expire_on_commit=False) if _engine_escrita is not None else None


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def criar_tabelas():
    """Aplica as migrações pendentes (Alembic) — cria o banco do zero ou atualiza um existente."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    raiz = Path(__file__).resolve().parent.parent
    cfg = Config(str(raiz / "alembic.ini"))
    cfg.set_main_option("script_location", str(raiz / "migrations"))
    cfg.attributes["sem_logging"] = True
    with engine.begin() as conexao:
        cfg.attributes["connection"] = conexao
        if engine.dialect.name == "postgresql":
            # vários processos subindo juntos: só um migra por vez (os outros esperam e já encontram tudo aplicado)
            conexao.exec_driver_sql("SELECT pg_advisory_xact_lock(727274001)")
        command.upgrade(cfg, "head")
