"""publicações próprias do administrador (notícias, dados, foto e vídeo) e fotos enviadas (guardadas no banco).

Reversão: `alembic downgrade 0017` (apaga as publicações e as fotos enviadas).

Revision ID: 0018
Revises: 0017
"""
import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "midias",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("nome", sa.String(120), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("tamanho", sa.Integer, nullable=False),
        sa.Column("dados", sa.LargeBinary, nullable=False),
        sa.Column("criada_em", sa.DateTime, nullable=False),
    )
    op.create_table(
        "publicacoes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("slug", sa.String(160), nullable=False, unique=True),
        sa.Column("titulo", sa.String(200), nullable=False),
        sa.Column("resumo", sa.String(400), nullable=True),
        sa.Column("corpo", sa.Text, nullable=False),
        sa.Column("categoria", sa.String(40), nullable=False, server_default="noticia"),
        sa.Column("capa_midia_id", sa.Integer, sa.ForeignKey("midias.id", ondelete="SET NULL", name="fk_publicacoes_capa_midia"), nullable=True),
        sa.Column("capa_url", sa.String(500), nullable=True),
        sa.Column("video_url", sa.String(300), nullable=True),
        sa.Column("fonte", sa.String(300), nullable=True),
        sa.Column("publicada", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("publicada_em", sa.DateTime, nullable=True),
        sa.Column("criada_em", sa.DateTime, nullable=False),
        sa.Column("atualizada_em", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("publicacoes")
    op.drop_table("midias")
