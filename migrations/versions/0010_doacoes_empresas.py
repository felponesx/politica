"""doações de campanha com CNPJ (empresa, partido, comitê) por candidatura

Só cria uma tabela nova; nenhum dado existente é tocado. Reversão: `alembic downgrade 0009`.

Revision ID: 0010
Revises: 0009
"""
import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "doacoes_empresas",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("ano", sa.Integer, nullable=False),
        sa.Column("cnpj", sa.String(14), nullable=False),
        sa.Column("doador", sa.String(200)),
        sa.Column("sq_candidato", sa.String(20), nullable=False),
        sa.Column("candidato", sa.String(200)),
        sa.Column("cargo", sa.String(60)),
        sa.Column("uf", sa.String(2)),
        sa.Column("partido", sa.String(30)),
        sa.Column("origem", sa.String(120), nullable=False),
        sa.Column("tipo_doador", sa.String(20), nullable=False),
        sa.Column("valor", sa.Float, nullable=False),
        sa.Column("n_doacoes", sa.Integer, nullable=False),
        sa.Column("primeira_data", sa.Date),
        sa.Column("ultima_data", sa.Date),
        sa.Column("coletado_em", sa.DateTime),
        sa.UniqueConstraint("ano", "cnpj", "sq_candidato", "origem", name="uq_doacao_empresa"),
    )
    for c in ("ano", "cnpj", "sq_candidato", "uf", "partido", "tipo_doador"):
        op.create_index(f"ix_doacoes_empresas_{c}", "doacoes_empresas", [c])


def downgrade() -> None:
    op.drop_table("doacoes_empresas")
