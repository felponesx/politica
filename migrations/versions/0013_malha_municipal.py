"""malha municipal versionada (origem, versão e geometria de cada município), com histórico

Só CRIA duas tabelas; nenhum dado existente é tocado. Cada importação é uma linha em `malha_fonte` (IBGE oficial, OSM provisório…) e suas geometrias ficam em `malha_municipio`.
Trocar a geometria usada NÃO apaga nada: vira `ativa=false` na antiga e `ativa=true` na nova (índice único parcial: no máximo uma ativa por município).
Reversão: `alembic downgrade 0012` (apaga só estas duas tabelas).

Revision ID: 0013
Revises: 0012
"""
import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "malha_fonte",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("origem", sa.String(20), nullable=False),            # ibge | osm | outra (identificada em `rotulo`)
        sa.Column("oficial", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("escopo", sa.String(40), nullable=False, server_default="municipios"),
        sa.Column("versao", sa.String(60), nullable=False),
        sa.Column("rotulo", sa.String(120)),
        sa.Column("publicado_em", sa.String(40)),                       # data da fonte (Last-Modified do arquivo ou carimbo da base OSM)
        sa.Column("coletado_em", sa.DateTime, nullable=False),
        sa.Column("url", sa.Text),
        sa.Column("sha256", sa.String(64)),
        sa.Column("etag", sa.String(80)),
        sa.Column("tamanho", sa.BigInteger),
        sa.Column("arquivo_local", sa.Text),
        sa.Column("status", sa.String(20), nullable=False, server_default="provisoria"),   # validada | provisoria | reprovada | substituida
        sa.Column("n_municipios", sa.Integer, nullable=False, server_default="0"),
        sa.Column("n_validos", sa.Integer, nullable=False, server_default="0"),
        sa.Column("n_invalidos", sa.Integer, nullable=False, server_default="0"),
        sa.Column("verificacao", sa.JSON),
        sa.UniqueConstraint("origem", "versao", name="uq_malha_fonte_versao"),
    )
    op.create_table(
        "malha_municipio",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("fonte_id", sa.Integer, sa.ForeignKey("malha_fonte.id", name="fk_malha_municipio_fonte", ondelete="RESTRICT"), nullable=False),
        sa.Column("cod_ibge", sa.String(7), nullable=False),
        sa.Column("nome", sa.String(120)),
        sa.Column("uf", sa.String(2)),
        sa.Column("geom_wkb", sa.LargeBinary),
        sa.Column("tolerancia_graus", sa.Float),                         # simplificação aplicada à geometria guardada (área e perímetro vêm da geometria completa)
        sa.Column("area_km2", sa.Float),
        sa.Column("perimetro_km", sa.Float),
        sa.Column("valida", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("motivo", sa.Text),
        sa.Column("ativa", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("fonte_id", "cod_ibge", name="uq_malha_municipio"),
    )
    op.create_index("ix_malha_municipio_cod", "malha_municipio", ["cod_ibge"])
    op.create_index("ix_malha_municipio_uf", "malha_municipio", ["uf"])
    op.create_index("uq_malha_municipio_ativa", "malha_municipio", ["cod_ibge"], unique=True, postgresql_where=sa.text("ativa"), sqlite_where=sa.text("ativa"))


def downgrade() -> None:
    op.drop_table("malha_municipio")
    op.drop_table("malha_fonte")
