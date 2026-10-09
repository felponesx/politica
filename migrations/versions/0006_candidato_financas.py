"""patrimônio e contas de campanha dos candidatos (TSE)

Revision ID: 0006
Revises: 0005
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    j = lambda: sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    op.create_table(
        "candidato_financas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ano", sa.Integer(), nullable=False),
        sa.Column("sq_candidato", sa.String(20), nullable=False),
        sa.Column("uf", sa.String(2)),
        sa.Column("patrimonio", sa.Float()), sa.Column("bens", j(), nullable=True), sa.Column("bens_por_tipo", j(), nullable=True),
        sa.Column("receitas", sa.Float()), sa.Column("receitas_por_fonte", j(), nullable=True),
        sa.Column("despesas", sa.Float()), sa.Column("despesas_por_tipo", j(), nullable=True),
        sa.UniqueConstraint("ano", "sq_candidato", name="uq_candidato_financas"),
    )
    for c in ("ano", "sq_candidato", "uf"):
        op.create_index(f"ix_candidato_financas_{c}", "candidato_financas", [c])


def downgrade() -> None:
    op.drop_table("candidato_financas")
