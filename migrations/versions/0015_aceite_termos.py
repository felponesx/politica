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
    # idempotente: um banco criado por outra versão deste branch pode já ter estas colunas
    colunas = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("contas")}
    if "termos_versao" not in colunas:
        op.add_column("contas", sa.Column("termos_versao", sa.String(20), nullable=True))
    if "termos_aceitos_em" not in colunas:
        op.add_column("contas", sa.Column("termos_aceitos_em", sa.DateTime, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("contas") as b:
        b.drop_column("termos_aceitos_em")
        b.drop_column("termos_versao")
