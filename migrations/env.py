from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app import models  # noqa: F401  (registra as tabelas)
from app.config import settings
from app.db import Base

config = context.config
if config.config_file_name is not None and not config.attributes.get("sem_logging"):
    fileConfig(config.config_file_name, disable_existing_loggers=False)
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    conexao = config.attributes.get("connection")
    if conexao is None:
        engine = engine_from_config(config.get_section(config.config_ini_section, {}),
                                    prefix="sqlalchemy.", poolclass=pool.NullPool)
        with engine.connect() as conexao:
            _rodar(conexao)
    else:
        _rodar(conexao)


def _rodar(conexao):
    # render_as_batch: permite ALTER TABLE também no SQLite
    context.configure(connection=conexao, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
