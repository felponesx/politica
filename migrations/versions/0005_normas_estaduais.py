"""normas estaduais: esfera e UF na tabela de normas

Revision ID: 0005
Revises: 0004
"""
import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("normas") as b:
        b.add_column(sa.Column("esfera", sa.String(10), nullable=False, server_default="federal"))
        b.add_column(sa.Column("uf", sa.String(2), nullable=True))
        b.create_index("ix_normas_esfera", ["esfera"])
        b.create_index("ix_normas_uf", ["uf"])


def downgrade() -> None:
    with op.batch_alter_table("normas") as b:
        b.drop_index("ix_normas_uf")
        b.drop_index("ix_normas_esfera")
        b.drop_column("uf")
        b.drop_column("esfera")
