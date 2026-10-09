"""fontes v0.2: municípios, indicadores municipais, dívida ativa (PGFN), cadastro CNPJ e desastres

Revision ID: 0004
Revises: 0003
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels = None
depends_on = None


def _json():
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "municipios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("codigo_ibge", sa.String(7), nullable=False, unique=True),
        sa.Column("nome", sa.String(120), nullable=False),
        sa.Column("uf", sa.String(2), nullable=False),
        sa.Column("microrregiao", sa.String(120)),
        sa.Column("populacao", sa.Integer()),
        sa.Column("populacao_ano", sa.Integer()),
        sa.Column("pib", sa.Float()),
        sa.Column("pib_ano", sa.Integer()),
        sa.Column("capag", sa.String(10)),
        sa.Column("capag_ano", sa.Integer()),
        sa.Column("capag_detalhe", _json(), nullable=True),
        sa.Column("atualizado_em", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_municipios_nome", "municipios", ["nome"])
    op.create_index("ix_municipios_uf", "municipios", ["uf"])
    op.create_index("ix_municipios_capag", "municipios", ["capag"])

    op.create_table(
        "indicadores_municipais",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("codigo_ibge", sa.String(7), nullable=False),
        sa.Column("uf", sa.String(2)),
        sa.Column("nome", sa.String(60), nullable=False),
        sa.Column("descricao", sa.String(300)),
        sa.Column("ano", sa.Integer(), nullable=False),
        sa.Column("valor", sa.Float()),
        sa.Column("unidade", sa.String(60)),
        sa.Column("fonte", sa.String(120)),
        sa.UniqueConstraint("codigo_ibge", "nome", "ano", name="uq_indicadores_municipais"),
    )
    for c in ("codigo_ibge", "uf", "nome", "ano"):
        op.create_index(f"ix_indicadores_municipais_{c}", "indicadores_municipais", [c])

    op.create_table(
        "devedores_pgfn",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cnpj", sa.String(14), nullable=False),
        sa.Column("nome", sa.String(300)),
        sa.Column("uf", sa.String(2)),
        sa.Column("tipo_divida", sa.String(30), nullable=False),
        sa.Column("inscricoes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valor", sa.Float(), nullable=False, server_default="0"),
        sa.Column("valor_ajuizado", sa.Float(), nullable=False, server_default="0"),
        sa.Column("referencia", sa.String(12), nullable=False),
        sa.UniqueConstraint("cnpj", "tipo_divida", "referencia", name="uq_devedores_pgfn"),
    )
    for c in ("cnpj", "nome", "uf", "valor", "referencia"):
        op.create_index(f"ix_devedores_pgfn_{c}", "devedores_pgfn", [c])

    op.create_table(
        "empresas_cadastro",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cnpj", sa.String(14), nullable=False, unique=True),
        sa.Column("razao_social", sa.String(300)),
        sa.Column("nome_fantasia", sa.String(300)),
        sa.Column("cnae", sa.String(10)),
        sa.Column("cnae_descricao", sa.String(300)),
        sa.Column("municipio", sa.String(120)),
        sa.Column("uf", sa.String(2)),
        sa.Column("situacao", sa.String(60)),
        sa.Column("abertura", sa.Date()),
        sa.Column("capital_social", sa.Float()),
        sa.Column("porte", sa.String(60)),
        sa.Column("natureza_juridica", sa.String(200)),
        sa.Column("socios", _json(), nullable=True),
        sa.Column("atualizado_em", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    for c in ("razao_social", "cnae", "uf"):
        op.create_index(f"ix_empresas_cadastro_{c}", "empresas_cadastro", [c])

    op.create_table(
        "ocorrencias_desastre",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("chave", sa.String(40), nullable=False, unique=True),
        sa.Column("codigo_ibge", sa.String(7)),
        sa.Column("municipio", sa.String(120)),
        sa.Column("uf", sa.String(2)),
        sa.Column("data", sa.Date()),
        sa.Column("tipo", sa.String(200)),
        sa.Column("cobrade", sa.String(20)),
        sa.Column("situacao", sa.String(120)),
        sa.Column("fonte", sa.String(60)),
    )
    for c in ("codigo_ibge", "uf", "data", "tipo"):
        op.create_index(f"ix_ocorrencias_desastre_{c}", "ocorrencias_desastre", [c])
    if op.get_bind().dialect.name == "postgresql":  # busca por nome de cidade (sem acento, por trigramas)
        op.execute("CREATE INDEX IF NOT EXISTS ix_municipios_busca_nome ON municipios USING gin (f_unaccent(nome) gin_trgm_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_municipios_busca_nome")
    for t in ("ocorrencias_desastre", "empresas_cadastro", "devedores_pgfn", "indicadores_municipais", "municipios"):
        op.drop_table(t)
