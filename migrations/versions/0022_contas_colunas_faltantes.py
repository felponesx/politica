"""repara a tabela `contas` de um banco que já passou pelas migrações 0015-0017 por outra versão do branch (carimbado adiante, sem as colunas).
Só ADICIONA o que falta; não mexe em nada que já existe.

Reversão: não há (só acrescentava colunas nulas).
"""
import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

COLUNAS = [
    ("google_sub", sa.String(64), {}),
    ("papel", sa.String(12), {"nullable": False, "server_default": "usuario"}),
    ("termos_versao", sa.String(20), {}),
    ("termos_aceitos_em", sa.DateTime, {}),
    ("data_nascimento", sa.Date, {}),
    ("uf", sa.String(2), {}),
    ("cidade", sa.String(80), {}),
    ("interesses", sa.String(300), {}),
    ("bloqueada", sa.Boolean, {"nullable": False, "server_default": sa.false()}),
    ("permissoes", sa.JSON, {}),
]


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if "contas" not in insp.get_table_names():
        return
    existentes = {c["name"] for c in insp.get_columns("contas")}
    for nome, tipo, extra in COLUNAS:
        if nome not in existentes:
            op.add_column("contas", sa.Column(nome, tipo, **({"nullable": True} | extra)))
    if "google_sub" not in existentes:
        op.create_index("uq_contas_google_sub", "contas", ["google_sub"], unique=True)


def downgrade() -> None:
    pass
