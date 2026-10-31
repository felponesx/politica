"""estoque de referência do Novo CAGED por município e subclasse

Só cria uma tabela nova; nenhum dado existente é tocado. Reversão: `alembic downgrade 0010`.

Revision ID: 0011
Revises: 0010
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "caged_estoque_ref",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("competencia", sa.String(7), nullable=False),
        sa.Column("cod_municipio", sa.String(6), nullable=False),
        sa.Column("subclasse", sa.String(7), nullable=False),
        sa.Column("vinculos", sa.Integer, nullable=False),
        sa.UniqueConstraint("competencia", "cod_municipio", "subclasse", name="uq_caged_estoque_ref"),
    )
    for c in ("competencia", "cod_municipio", "subclasse"):
        op.create_index(f"ix_caged_estoque_ref_{c}", "caged_estoque_ref", [c])


def downgrade() -> None:
    op.drop_table("caged_estoque_ref")
