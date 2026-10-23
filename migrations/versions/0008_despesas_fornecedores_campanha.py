"""maiores fornecedores das despesas de campanha (TSE)

Só acrescenta uma coluna opcional; nenhum dado existente é tocado. Reversão: `alembic downgrade 0007`.

Revision ID: 0008
Revises: 0007
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("candidato_financas") as b:
        b.add_column(sa.Column("despesas_fornecedores", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("candidato_financas") as b:
        b.drop_column("despesas_fornecedores")
