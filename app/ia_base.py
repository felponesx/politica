"""Utilitários comuns da IA própria (formato da resposta, valores em reais, fontes). Sem rede e sem modelo."""

FONTE_COTA = "Cota parlamentar: Câmara dos Deputados (cota para o exercício da atividade parlamentar) e Senado (CEAPS), dados abertos."
FONTE_CADASTRO = "Cadastro de parlamentares: Câmara dos Deputados e Senado Federal, dados abertos."
FONTE_TSE = "Tribunal Superior Eleitoral (TSE), dados abertos de candidaturas e prestação de contas."
FONTE_TRAMITACAO = "Câmara dos Deputados e Senado Federal: proposições e tramitação (dados abertos)."
FONTE_VOTACOES = "Câmara dos Deputados e Senado Federal: votações nominais (dados abertos)."
FONTE_EMENDAS = "Portal da Transparência (CGU): emendas parlamentares."


def brl(v: float) -> str:
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def entendi(e: dict) -> str:
    """Se o nome achado não é igual ao digitado, diz quem foi entendido (a pessoa pode corrigir)."""
    _i, nome, nota = e["pessoas"][0]
    return f"Entendi que você se refere a {nome}. " if nota < 0.97 else ""


def plural(n: int, singular: str, plural_: str) -> str:
    return f"{n} {singular if n == 1 else plural_}"


def cargo(casa: str | None) -> str:
    return {"camara": "deputado(a) federal", "senado": "senador(a)"}.get(casa or "", "parlamentar")


def resposta(entendeu: bool, intencao: str | None, texto: str, fontes: list[str] | None = None, dados: dict | None = None,
             aviso: str | None = None, sugestoes: list[str] | None = None) -> dict:
    return {"entendeu": entendeu, "intencao": intencao, "resposta": texto, "fontes": fontes or [], "dados": dados or {},
            "aviso": aviso, "sugestoes": sugestoes or []}
