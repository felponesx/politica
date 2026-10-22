from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

_connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
if settings.database_url.startswith("postgres") and settings.somente_leitura and settings.consulta_timeout_ms > 0:
    # API pública: uma consulta pesada não segura o banco (as coletas, que usam outro processo, não têm esse limite)
    _connect_args["options"] = f"-c statement_timeout={int(settings.consulta_timeout_ms)}"
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


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
        command.upgrade(cfg, "head")
