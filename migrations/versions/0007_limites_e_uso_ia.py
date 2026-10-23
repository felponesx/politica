"""contadores compartilhados de limite, registro de uso da IA e cache da IA

Só cria tabelas novas (nenhum dado existente é tocado). Reversão: `alembic downgrade 0006` apaga só estas 3 tabelas.
No Postgres, o usuário só-leitura da API (brasil_leitura) ganha escrita APENAS nestas 3 tabelas.

Revision ID: 0007
Revises: 0006
"""
import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "uso_limites",
        sa.Column("chave", sa.String(160), nullable=False), sa.Column("janela", sa.Integer(), nullable=False),
        sa.Column("n", sa.Integer(), nullable=False, server_default="0"), sa.Column("atualizado", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("chave", "janela", name="pk_uso_limites"),
    )
    op.create_index("ix_uso_limites_atualizado", "uso_limites", ["atualizado"])
    op.create_table(
        "uso_ia",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("quando", sa.Integer(), nullable=False),
        sa.Column("rota", sa.String(20), nullable=False), sa.Column("cliente", sa.String(16), nullable=False),
        sa.Column("resultado", sa.String(20), nullable=False),
        sa.Column("custo_micro_usd", sa.Integer(), nullable=False, server_default="0"), sa.Column("ms", sa.Integer()),
    )
    op.create_index("ix_uso_ia_quando", "uso_ia", ["quando"])
    op.create_table(
        "cache_ia",
        sa.Column("chave", sa.String(64), primary_key=True), sa.Column("valor", sa.Text(), nullable=False),
        sa.Column("expira", sa.Integer(), nullable=False),
    )
    op.create_index("ix_cache_ia_expira", "cache_ia", ["expira"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'brasil_leitura') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE ON uso_limites, uso_ia, cache_ia TO brasil_leitura;
                GRANT USAGE, SELECT ON SEQUENCE uso_ia_id_seq TO brasil_leitura;
            END IF; END $$;""")


def downgrade() -> None:
    op.drop_table("cache_ia")
    op.drop_table("uso_ia")
    op.drop_table("uso_limites")
