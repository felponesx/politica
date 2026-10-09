"""Fluxo federativo: arrecadado × redistribuído × retornado, por estado e ano.

Definições (também devolvidas na API, para o site exibir):
- arrecadado: tributos federais recolhidos na UF (Receita Federal).
- redistribuido_pais: total de transferências constitucionais/legais da União
  a TODOS os estados e municípios no ano (Tesouro).
- retornado: transferências recebidas pelo governo do estado + soma dos municípios da UF.
"""
from sqlalchemy import func, select

from app.models import Registro

METODOLOGIA = {
    "arrecadado": "Tributos federais recolhidos na UF, segundo a Receita Federal (arrecadação por estado).",
    "redistribuido_pais": "Soma das transferências constitucionais e legais da União a todos os estados e municípios "
                          "(FPE, FPM, Fundeb, IPI-Exp, CIDE, royalties etc.), segundo o Tesouro Nacional.",
    "retornado": "Transferências constitucionais e legais recebidas pelo governo do estado e por seus municípios.",
    "limitacoes": [
        "A Receita registra o tributo onde está o domicílio fiscal da empresa (geralmente a sede), "
        "o que aumenta artificialmente a arrecadação de SP, RJ e DF.",
        "Só entram transferências obrigatórias. Ficam de fora gastos diretos da União no estado "
        "(salários federais, aposentadorias do INSS, Bolsa Família, obras) e transferências voluntárias (convênios).",
        "Valores nominais (sem correção pela inflação), regime de caixa.",
        "O FPE e o FPM já vêm descontados da parcela de 20% que vai para o Fundeb; o repasse do Fundeb aparece "
        "como transferência própria (não há dupla contagem).",
    ],
}


def _soma(db, tipos: list[str], ano: int, uf: str | None = None) -> float | None:
    stmt = select(func.sum(Registro.valor)).where(Registro.tipo.in_(tipos), Registro.ano == ano)
    if uf:
        stmt = stmt.where(Registro.uf == uf)
    v = db.scalar(stmt)
    return round(v, 2) if v is not None else None


def _div(a, b):
    return round(a / b, 4) if a is not None and b else None


def fluxo_estado(db, uf: str, ano: int) -> dict:
    arrecadado = _soma(db, ["arrecadacao_uf"], ano, uf)
    arrecadado_pais = _soma(db, ["arrecadacao_uf"], ano)
    ret_estado = _soma(db, ["transf_estado"], ano, uf)
    ret_munic = _soma(db, ["transf_municipios"], ano, uf)
    retornado = None if ret_estado is None and ret_munic is None else round((ret_estado or 0) + (ret_munic or 0), 2)
    redistribuido = _soma(db, ["transf_estado", "transf_municipios"], ano)
    return {
        "uf": uf, "ano": ano,
        "arrecadado": arrecadado,
        "redistribuido_pais": redistribuido,
        "retornado": retornado,
        "retornado_detalhe": {"governo_estadual": ret_estado, "municipios": ret_munic},
        "retorno_por_real_arrecadado": _div(retornado, arrecadado),
        "participacao_arrecadacao_nacional": _div(arrecadado, arrecadado_pais),
        "participacao_nas_transferencias": _div(retornado, redistribuido),
        "saldo": round(arrecadado - retornado, 2) if arrecadado is not None and retornado is not None else None,
        "status": "ok" if arrecadado is not None and retornado is not None else "dados incompletos — rode as coletas receita-arrecadacao e tesouro-transferencias",
    }


def ultimo_ano_completo(db) -> int | None:
    """Último ano que tem os 12 meses de arrecadação."""
    linhas = db.execute(select(Registro.ano, func.count()).where(Registro.tipo == "arrecadacao_uf")
                        .group_by(Registro.ano).order_by(Registro.ano.desc())).all()
    return next((a for a, c in linhas if c >= 27 * 12), linhas[0][0] if linhas else None)
