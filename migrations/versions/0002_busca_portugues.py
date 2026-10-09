"""busca em português (Postgres): unaccent, full-text e trigramas

Revision ID: 0002
Revises: 0001
"""
from alembic import op

from app.busca import ENTIDADES as _TODAS, tsvector

# tabelas que existiam nesta versão (as criadas depois ganham o índice na própria migração)
ENTIDADES = {k: v for k, v in _TODAS.items()
             if k in ("parlamentares", "candidatos", "proposicoes", "normas", "votacoes", "contratos", "obras")}

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return  # SQLite usa LIKE; nada a criar
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    # unaccent não é IMMUTABLE; este invólucro é, e por isso pode ser usado em índices
    op.execute("""
        CREATE OR REPLACE FUNCTION f_unaccent(text) RETURNS text
        LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
        AS $$ SELECT public.unaccent('public.unaccent'::regdictionary, $1) $$
    """)
    for tabela, (expr, modo, _, _) in ENTIDADES.items():
        if modo == "texto":
            op.execute(f"CREATE INDEX IF NOT EXISTS ix_{tabela}_busca ON {tabela} USING gin ({tsvector(expr)})")
        else:
            op.execute(f"CREATE INDEX IF NOT EXISTS ix_{tabela}_busca_nome ON {tabela} USING gin (f_unaccent({expr}) gin_trgm_ops)")
    # índices de apoio para filtros comuns do site
    op.execute("CREATE INDEX IF NOT EXISTS ix_contratos_uf_ano_valor ON contratos (uf, ano, valor DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_registros_tipo_uf_ano ON registros (tipo, uf, ano)")


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    for tabela, (_, modo, _, _) in ENTIDADES.items():
        op.execute(f"DROP INDEX IF EXISTS ix_{tabela}_busca{'' if modo == 'texto' else '_nome'}")
    op.execute("DROP INDEX IF EXISTS ix_contratos_uf_ano_valor")
    op.execute("DROP INDEX IF EXISTS ix_registros_tipo_uf_ano")
    op.execute("DROP FUNCTION IF EXISTS f_unaccent(text)")
