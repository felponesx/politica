"""aceite dos termos de uso no cadastro (versão e data). Só ADICIONA colunas nulas; contas antigas ficam sem aceite registrado.

Reversão: `alembic downgrade 0014`.

Revision ID: 0015
Revises: 0014
"""
import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contas", sa.Column("termos_versao", sa.String(20), nullable=True))
    op.add_column("contas", sa.Column("termos_aceitos_em", sa.DateTime, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("contas") as b:
        b.drop_column("termos_aceitos_em")
        b.drop_column("termos_versao")
