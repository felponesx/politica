"""cursos, eventos e concursos (tabela nova; só cria, não altera nada existente)

Revises: 0015
"""
import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oportunidades",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tipo", sa.String(12), nullable=False),
        sa.Column("titulo", sa.String(300), nullable=False),
        sa.Column("orgao", sa.String(200)),
        sa.Column("uf", sa.String(2)),
        sa.Column("cidade", sa.String(120)),
        sa.Column("data_inicio", sa.Date),
        sa.Column("data_fim", sa.Date),
        sa.Column("inscricoes_ate", sa.Date),
        sa.Column("link", sa.String(500), nullable=False),
        sa.Column("fonte", sa.String(200)),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("criada_em", sa.DateTime, nullable=False),
        sa.Column("aprovada_em", sa.DateTime),
        sa.UniqueConstraint("tipo", "link", name="uq_oportunidade_tipo_link"),
    )
    op.create_index("ix_oportunidades_tipo", "oportunidades", ["tipo"])
    op.create_index("ix_oportunidades_uf", "oportunidades", ["uf"])
    op.create_index("ix_oportunidades_status", "oportunidades", ["status"])


def downgrade() -> None:
    op.drop_table("oportunidades")
