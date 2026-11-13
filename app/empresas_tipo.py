"""Tipo de cada empresa: pública, de economia mista, privada, concessão de serviço público etc.

- Tipo jurídico: natureza jurídica do CNPJ (tabela da Receita Federal). 2011 = empresa pública (capital 100% do governo);
  2038 = sociedade de economia mista (o governo controla, com sócios privados); 1xxx = administração pública; 3xxx = sem fins
  lucrativos; cooperativas; o resto das entidades empresariais (2xxx) = privada.
- Controle acionário (só companhias abertas): informado à CVM (estatal, privado, estrangeiro). Uma S.A. "privada" no papel pode
  ser controlada pelo governo (subsidiária de estatal) — por isso o controle aparece à parte.
- Concessão de serviço público: pela ATIVIDADE principal registrada na Receita (CNAE) em setores que o poder público concede
  (energia, água e esgoto, rodovias, ferrovias, aeroportos, portos, gás canalizado, telefonia fixa, ônibus). É um indício pela
  atividade, não a conferência do contrato de concessão.
"""
from __future__ import annotations

TIPOS = {
    "empresa_publica": "Empresa pública",
    "economia_mista": "Economia mista",
    "entidade_publica": "Órgão ou entidade pública",
    "privada": "Privada",
    "cooperativa": "Cooperativa",
    "sem_fins_lucrativos": "Sem fins lucrativos",
    "internacional": "Organização internacional",
}

EXPLICA = {
    "empresa_publica": "Empresa com capital 100% do governo (ex.: Caixa, Correios, BNDES).",
    "economia_mista": "Empresa controlada pelo governo, com ações também de sócios privados (ex.: Petrobras, Banco do Brasil).",
    "entidade_publica": "Órgão, autarquia ou fundação da administração pública.",
    "privada": "Empresa de dono privado (pessoas ou outras empresas).",
    "cooperativa": "Cooperativa: empresa dos próprios associados.",
    "sem_fins_lucrativos": "Associação, fundação privada ou entidade sem fins lucrativos.",
    "internacional": "Organização internacional.",
    "concessao": "Atua num serviço público que o governo concede a empresas (pela atividade registrada na Receita; não confere o contrato).",
}

# CNAE (7 dígitos) de serviços públicos concedidos -> setor
CONCESSAO_CNAE = {
    "3511501": "Energia (geração)", "3512300": "Energia (transmissão)", "3514000": "Energia (distribuição)",
    "3520402": "Gás canalizado",
    "3600601": "Água e esgoto", "3701100": "Água e esgoto",
    "5221400": "Rodovias",
    "4911600": "Ferrovias (carga)", "4912401": "Trens de passageiros", "4912402": "Trens de passageiros", "4912403": "Metrô",
    "5240101": "Aeroportos",
    "5231101": "Portos", "5231102": "Portos",
    "6110801": "Telefonia fixa",
    "4921301": "Ônibus urbano", "4921302": "Ônibus metropolitano",
}

COOPERATIVAS = {2143, 2330}


def tipo_por_natureza(codigo) -> str | None:
    try:
        c = int(str(codigo).replace("-", "").strip())
    except (TypeError, ValueError):
        return None
    if c == 2011:
        return "empresa_publica"
    if c == 2038:
        return "economia_mista"
    if c in COOPERATIVAS:
        return "cooperativa"
    if 1000 <= c < 2000:
        return "entidade_publica"
    if 2000 <= c < 3000:
        return "privada"
    if 3000 <= c < 4000:
        return "sem_fins_lucrativos"
    if 5000 <= c < 6000:
        return "internacional"
    return None


def concessao(cnae) -> str | None:
    c = "".join(ch for ch in str(cnae or "") if ch.isdigit())
    return CONCESSAO_CNAE.get(c.zfill(7)) if c else None


def controle_cvm(texto: str | None) -> str | None:
    t = (texto or "").upper()
    if t.startswith("ESTATAL"):
        return "estatal"
    if t.startswith("ESTRANGEIRO"):
        return "estrangeiro"
    if t.startswith("PRIVADO"):
        return "privado"
    return None


def do_governo(e: dict) -> bool:
    """Empresa do governo: empresa pública, economia mista ou companhia aberta de controle estatal."""
    return e.get("tipo") in ("empresa_publica", "economia_mista") or e.get("controle") == "estatal"


def cnpj_matriz(basico: str) -> str:
    """CNPJ completo da matriz (0001) a partir dos 8 primeiros dígitos, com os dígitos verificadores."""
    b = "".join(ch for ch in str(basico) if ch.isdigit()).zfill(8)[:8] + "0001"

    def dv(n: str) -> str:
        pesos = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2] if len(n) == 12 else [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        r = sum(int(a) * p for a, p in zip(n, pesos)) % 11
        return "0" if r < 2 else str(11 - r)

    d1 = dv(b)
    return b + d1 + dv(b + d1)
