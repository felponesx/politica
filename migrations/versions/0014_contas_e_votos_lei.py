"""contas de pessoas, sessões de login e votos nas leis (uma conta = um voto por lei)

Só CRIA três tabelas; nenhum dado existente é tocado. Senha guardada como hash; CPF só como código HMAC.
Reversão: `alembic downgrade 0013` (apaga só estas três tabelas).

Revision ID: 0014
Revises: 0013
"""
import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contas",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(254), nullable=False, unique=True),
        sa.Column("senha_hash", sa.String(200), nullable=False),
        sa.Column("cpf_codigo", sa.String(64), nullable=False, unique=True),
        sa.Column("nome", sa.String(120), nullable=False),
        sa.Column("criada_em", sa.DateTime, nullable=False),
    )
    op.create_table(
        "sessoes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("conta_id", sa.Integer, sa.ForeignKey("contas.id", ondelete="CASCADE", name="fk_sessoes_conta"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expira_em", sa.DateTime, nullable=False),
    )
    op.create_index("ix_sessoes_conta_id", "sessoes", ["conta_id"])
    op.create_index("ix_sessoes_expira_em", "sessoes", ["expira_em"])
    op.create_table(
        "votos_lei",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("conta_id", sa.Integer, sa.ForeignKey("contas.id", ondelete="CASCADE", name="fk_votos_lei_conta"), nullable=False),
        sa.Column("proposicao_id", sa.Integer, sa.ForeignKey("proposicoes.id", ondelete="CASCADE", name="fk_votos_lei_proposicao"), nullable=False),
        sa.Column("opcao", sa.String(12), nullable=False),
        sa.Column("atualizado_em", sa.DateTime, nullable=False),
        sa.UniqueConstraint("conta_id", "proposicao_id", name="uq_votos_lei_conta_proposicao"),
    )
    op.create_index("ix_votos_lei_conta_id", "votos_lei", ["conta_id"])
    op.create_index("ix_votos_lei_proposicao_id", "votos_lei", ["proposicao_id"])


def downgrade() -> None:
    op.drop_table("votos_lei")
    op.drop_table("sessoes")
    op.drop_table("contas")
