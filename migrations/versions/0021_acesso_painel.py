"""acesso ao painel: conta pode ser bloqueada e ter permissões por seção (só ADICIONA colunas; contas antigas ficam liberadas e sem permissão extra).

Reversão: `alembic downgrade 0020`.
"""
import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    colunas = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("contas")}
    if "bloqueada" not in colunas:
        op.add_column("contas", sa.Column("bloqueada", sa.Boolean, nullable=False, server_default=sa.false()))
    if "permissoes" not in colunas:
        op.add_column("contas", sa.Column("permissoes", sa.JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("contas") as b:
        b.drop_column("permissoes")
        b.drop_column("bloqueada")
