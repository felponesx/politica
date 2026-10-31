"""onde cada instituição de ensino superior oferece cursos (Censo da Educação Superior)

Só cria uma tabela nova; nenhum dado existente é tocado. Reversão: `alembic downgrade 0011`.

Revision ID: 0012
Revises: 0011
"""
import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ies_municipio",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ano_censo", sa.Integer, nullable=False),
        sa.Column("co_ies", sa.Integer, nullable=False),
        sa.Column("nome", sa.String(200)),
        sa.Column("sigla", sa.String(40)),
        sa.Column("cod_municipio", sa.String(7), nullable=False),
        sa.Column("municipio", sa.String(120)),
        sa.Column("uf", sa.String(2)),
        sa.Column("sede", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("n_cursos", sa.Integer, nullable=False, server_default="0"),
        sa.Column("vagas", sa.Integer, nullable=False, server_default="0"),
        sa.Column("matriculas", sa.Integer, nullable=False, server_default="0"),
        sa.UniqueConstraint("ano_censo", "co_ies", "cod_municipio", name="uq_ies_municipio"),
    )
    for c in ("ano_censo", "co_ies", "cod_municipio", "uf"):
        op.create_index(f"ix_ies_municipio_{c}", "ies_municipio", [c])


def downgrade() -> None:
    op.drop_table("ies_municipio")
