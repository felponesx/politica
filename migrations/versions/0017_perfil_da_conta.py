"""perfil da conta: data de nascimento, UF, cidade e interesses (todos opcionais). Só ADICIONA colunas nulas.

Reversão: `alembic downgrade 0016`.

Revision ID: 0017
Revises: 0016
"""
import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contas", sa.Column("data_nascimento", sa.Date, nullable=True))
    op.add_column("contas", sa.Column("uf", sa.String(2), nullable=True))
    op.add_column("contas", sa.Column("cidade", sa.String(80), nullable=True))
    op.add_column("contas", sa.Column("interesses", sa.String(300), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("contas") as b:
        b.drop_column("interesses")
        b.drop_column("cidade")
        b.drop_column("uf")
        b.drop_column("data_nascimento")
