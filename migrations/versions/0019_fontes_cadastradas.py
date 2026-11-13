"""fontes cadastradas pela tela (sem git): a lista que o coletor do PC lê pela API

Só CRIA a tabela `fontes_cadastradas`; nenhum dado existente é tocado.
Reversão: `alembic downgrade 0014` (apaga só esta tabela).

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "fontes_cadastradas" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "fontes_cadastradas",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nome", sa.String(64), nullable=False, unique=True),
        sa.Column("produto", sa.String(60), nullable=False),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("intervalo_min", sa.Integer, nullable=False),
        sa.Column("formato", sa.String(10), nullable=False),
        sa.Column("campos", sa.JSON, nullable=False),
        sa.Column("permitir_pessoas", sa.Boolean, nullable=False),
        sa.Column("ativa", sa.Boolean, nullable=False),
        sa.Column("criada_em", sa.DateTime, nullable=False),
        sa.Column("atualizada_em", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("fontes_cadastradas")
