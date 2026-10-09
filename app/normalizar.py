"""Projeta o staging (`registros`) nas tabelas normalizadas.

Incremental: só processa registros novos ou atualizados desde a última normalização.
Rodado automaticamente depois de cada coleta (ver app/collectors/__init__.py) ou via
`python -m scripts.coletar normalizar`.
"""
import logging

from sqlalchemy import and_, or_, select

from app.db import SessionLocal
from app.models import Candidato, Contrato, FinancaEstadual, Indicador, Obra, Registro
from app.utils import cavar, para_data, para_float, pegar, sem_acento, so_digitos

log = logging.getLogger("brasilplus.normalizar")
LOTE = 2000


def _contrato(r: Registro) -> dict:
    d = r.dados or {}
    if r.fonte == "pncp":
        return dict(fonte="pncp", numero_controle=r.chave,
                    esfera=cavar(d, "orgaoEntidade", "esferaId"),
                    orgao=cavar(d, "orgaoEntidade", "razaoSocial"), cnpj_orgao=so_digitos(cavar(d, "orgaoEntidade", "cnpj")),
                    uf=r.uf, municipio=cavar(d, "unidadeOrgao", "municipioNome"),
                    fornecedor=d.get("nomeRazaoSocialFornecedor"), cnpj_fornecedor=so_digitos(d.get("niFornecedor")),
                    objeto=r.titulo, valor=r.valor, data_assinatura=para_data(d.get("dataAssinatura")),
                    vigencia_fim=para_data(d.get("dataVigenciaFim")), ano=r.ano)
    forn = d.get("fornecedor") or {}
    org = cavar(d, "unidadeGestora", "orgaoVinculado") or {}
    return dict(fonte="transparencia", numero_controle=str(pegar(d, "numero", "id") or r.chave), esfera="F",
                orgao=pegar(org, "nome"), cnpj_orgao=so_digitos(pegar(org, "cnpj")), uf=r.uf, municipio=None,
                fornecedor=pegar(forn, "nome", "razaoSocialReceita"), cnpj_fornecedor=so_digitos(pegar(forn, "cnpjFormatado", "cpfFormatado")),
                objeto=r.titulo, valor=r.valor, data_assinatura=para_data(pegar(d, "dataAssinatura", "dataInicioVigencia")),
                vigencia_fim=para_data(pegar(d, "dataFimVigencia")), ano=r.ano)


def _obra(r: Registro) -> dict:
    d = r.dados or {}
    fontes = d.get("fontesDeRecurso") or []
    federal = sum(para_float(f.get("valorInvestimentoPrevisto")) or 0 for f in fontes
                  if isinstance(f, dict) and sem_acento(f.get("origem") or "") == "FEDERAL")
    tipos = d.get("tipos") or []
    executores = d.get("executores") or []
    return dict(id_unico=r.chave, nome=r.titulo, descricao=d.get("descricao"), uf=r.uf,
                situacao=d.get("situacao"), natureza=d.get("natureza"), especie=d.get("especie"),
                tipo=(tipos[0] or {}).get("descricao") if tipos else None,
                executor=(executores[0] or {}).get("nome") if executores else None,
                valor_previsto=r.valor, valor_federal=federal or None,
                inicio_previsto=para_data(d.get("dataInicialPrevista")), fim_previsto=para_data(d.get("dataFinalPrevista")))


def _candidato(r: Registro) -> dict:
    d = r.dados or {}
    return dict(ano=r.ano, sq_candidato=d.get("SQ_CANDIDATO") or r.chave.split("-")[-1], numero=d.get("NR_CANDIDATO"),
                nome=d.get("NM_CANDIDATO"), nome_urna=d.get("NM_URNA_CANDIDATO"), partido=d.get("SG_PARTIDO"),
                uf=r.uf, unidade=d.get("NM_UE"), cargo=sem_acento(d.get("DS_CARGO") or "") or None,
                situacao_candidatura=d.get("DS_SITUACAO_CANDIDATURA"), resultado=d.get("DS_SIT_TOT_TURNO"),
                ocupacao=d.get("DS_OCUPACAO"), instrucao=d.get("DS_GRAU_INSTRUCAO"), genero=d.get("DS_GENERO"))


def _indicador(r: Registro) -> dict:
    d = r.dados or {}
    return dict(nome=r.tipo.split(":", 1)[1], descricao=r.titulo, uf=r.uf, periodo=str(d.get("periodo") or r.ano),
                ano=r.ano, valor=r.valor, unidade=d.get("unidade"))


def _financa(r: Registro) -> dict:
    d = r.dados or {}
    return dict(uf=r.uf, ano=r.ano, mes_ou_periodo=d.get("mes") or d.get("periodo"), demonstrativo=r.tipo,
                cod_conta=d.get("cod_conta"), conta=r.titulo, coluna=d.get("coluna"), valor=r.valor)


# (modelo destino, filtro do staging, função de conversão)
PROJECOES = {
    "contratos": (Contrato, Registro.tipo == "contrato", _contrato),
    "obras": (Obra, Registro.tipo == "obra", _obra),
    "candidatos": (Candidato, Registro.tipo == "candidato", _candidato),
    "indicadores": (Indicador, Registro.tipo.like("indicador:%"), _indicador),
    "financas": (FinancaEstadual, and_(Registro.fonte.in_(["siconfi", "receita", "tesouro"]),
                                       Registro.tipo != "despesa_funcao", Registro.uf.isnot(None)), _financa),
}

FONTE_PARA_PROJECAO = {"pncp": ["contratos"], "transparencia": ["contratos"], "obrasgov": ["obras"],
                       "tse": ["candidatos"], "ibge": ["indicadores"], "siconfi": ["financas"],
                       "receita": ["financas"], "tesouro": ["financas"]}


def normalizar(projecoes: list[str] | None = None) -> dict:
    resultado = {}
    db = SessionLocal()
    try:
        for nome in projecoes or PROJECOES:
            modelo, filtro, conv = PROJECOES[nome]
            total = 0
            while True:
                # registros sem linha normalizada, ou atualizados depois dela
                lote = db.execute(
                    select(Registro, modelo).outerjoin(modelo, modelo.registro_id == Registro.id)
                    .where(filtro, or_(modelo.id.is_(None), Registro.atualizado_em > modelo.normalizado_em))
                    .order_by(Registro.id).limit(LOTE)).all()
                if not lote:
                    break
                for reg, existente in lote:
                    valores = conv(reg)
                    if existente is None:
                        db.add(modelo(registro_id=reg.id, **valores))
                    else:
                        for k, v in valores.items():
                            setattr(existente, k, v)
                        existente.normalizado_em = reg.atualizado_em
                db.commit()
                total += len(lote)
                if len(lote) < LOTE:
                    break
            resultado[nome] = total
            log.info("Normalizados %s: %s", nome, total)
    finally:
        db.close()
    return resultado
