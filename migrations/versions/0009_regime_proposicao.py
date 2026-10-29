"""regime de tramitação das proposições (base da prioridade alta/média/baixa)

Só acrescenta uma coluna opcional. Reversão: `alembic downgrade 0008`.

Revision ID: 0009
Revises: 0008
"""
import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("proposicoes") as b:
        b.add_column(sa.Column("regime", sa.String(120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("proposicoes") as b:
        b.drop_column("regime")
