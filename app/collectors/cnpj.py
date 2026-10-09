"""Cadastro CNPJ e quadro societário — dados abertos da Receita Federal, consultados pela BrasilAPI.
Docs: https://brasilapi.com.br/docs#tag/CNPJ

Só consulta CNPJs que já aparecem nas bases do BRASIL+ (fornecedores de contratos e da cota parlamentar).
O CPF dos sócios já vem mascarado pela própria fonte.
"""
import logging
import time
from datetime import datetime, timedelta

from sqlalchemy import func, select

from app import http
from app.collectors.base import registrar_coleta
from app.config import settings
from app.models import Contrato, Despesa, EmpresaCadastro
from app.utils import para_data, para_float, pegar, upsert

log = logging.getLogger("brasilplus.cnpj")


def converter(d: dict) -> dict:
    socios = [{"nome": pegar(s, "nome_socio", "nome"), "qualificacao": pegar(s, "qualificacao_socio", "qualificacao"),
               "entrada": pegar(s, "data_entrada_sociedade"), "documento": pegar(s, "cnpj_cpf_do_socio"),
               "faixa_etaria": pegar(s, "faixa_etaria")} for s in (d.get("qsa") or [])]
    return {"razao_social": pegar(d, "razao_social"), "nome_fantasia": pegar(d, "nome_fantasia"),
            "cnae": str(pegar(d, "cnae_fiscal") or "")[:10] or None, "cnae_descricao": pegar(d, "cnae_fiscal_descricao"),
            "municipio": pegar(d, "municipio"), "uf": pegar(d, "uf"),
            "situacao": pegar(d, "descricao_situacao_cadastral", "situacao_cadastral"),
            "abertura": para_data(pegar(d, "data_inicio_atividade")), "capital_social": para_float(pegar(d, "capital_social")),
            "porte": pegar(d, "porte", "descricao_porte"), "natureza_juridica": pegar(d, "natureza_juridica"),
            "socios": socios}


def consultar(db, cnpj: str) -> EmpresaCadastro | None:
    try:
        d = http.get_json(settings.cnpj_api_url.format(cnpj=cnpj))
    except Exception as e:
        log.warning("CNPJ %s: %s", cnpj, e)
        return None
    if not d:
        return None
    return upsert(db, EmpresaCadastro, {"cnpj": cnpj}, converter(d))


def coletar_cnpj_fornecedores(limite: int = 300, dias: int = 90):
    """Atualiza o cadastro dos maiores fornecedores (por valor contratado + cota) que estão sem cadastro
    ou com cadastro mais velho que `dias`."""
    with registrar_coleta("receita", "cnpj_fornecedores", limite=limite) as (db, n):
        corte = datetime.now() - timedelta(days=dias)
        recentes = {c for (c,) in db.execute(select(EmpresaCadastro.cnpj).where(EmpresaCadastro.atualizado_em >= corte))}
        candidatos = [c for (c, _) in db.execute(
            select(Contrato.cnpj_fornecedor, func.sum(Contrato.valor)).where(func.length(Contrato.cnpj_fornecedor) == 14)
            .group_by(Contrato.cnpj_fornecedor).order_by(func.sum(Contrato.valor).desc()).limit(limite * 2))]
        candidatos += [c for (c, _) in db.execute(
            select(Despesa.cnpj_cpf, func.sum(Despesa.valor)).where(func.length(Despesa.cnpj_cpf) == 14)
            .group_by(Despesa.cnpj_cpf).order_by(func.sum(Despesa.valor).desc()).limit(limite))]
        feitos = 0
        for cnpj in dict.fromkeys(candidatos):
            if feitos >= limite:
                break
            if cnpj in recentes:
                continue
            if consultar(db, cnpj):
                n += 1
            feitos += 1
            db.commit()
            time.sleep(settings.cnpj_intervalo)
    return n.itens
