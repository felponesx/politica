"""conta Google (google_sub), papel de administrador (papel) e senha opcional (contas só com Google).

Reversão: `alembic downgrade 0015` (apaga as colunas novas; contas só com Google perdem o acesso).

Revision ID: 0016
Revises: 0015
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    colunas = {c["name"] for c in insp.get_columns("contas")}
    unicos = {u["name"] for u in insp.get_unique_constraints("contas")}
    with op.batch_alter_table("contas") as b:   # idempotente: pula o que já existe
        if "google_sub" not in colunas:
            b.add_column(sa.Column("google_sub", sa.String(64), nullable=True))
        if "papel" not in colunas:
            b.add_column(sa.Column("papel", sa.String(12), nullable=False, server_default="usuario"))
        b.alter_column("senha_hash", existing_type=sa.String(200), nullable=True)
        if "uq_contas_google_sub" not in unicos:
            b.create_unique_constraint("uq_contas_google_sub", ["google_sub"])


def downgrade() -> None:
    with op.batch_alter_table("contas") as b:
        b.drop_constraint("uq_contas_google_sub", type_="unique")
        b.drop_column("papel")
        b.drop_column("google_sub")
