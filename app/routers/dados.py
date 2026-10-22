import re
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collectors import TAREFAS
from app.config import settings
from app.db import get_db
from app.models import Coleta, Parlamentar, Registro
from app.schemas import ColetaOut, Pagina, RegistroOut
from app.fluxo import METODOLOGIA, fluxo_estado, ultimo_ano_completo
from app.utils import UFS

router = APIRouter()


@router.get("/registros", response_model=Pagina, tags=["Dados"])
def listar_registros(fonte: str | None = None, tipo: str | None = None, uf: str | None = None,
                     ano: int | None = None, q: str | None = None, limit: int = Query(50, ge=1, le=500),
                     offset: int = Query(0, ge=0, le=1_000_000), db: Session = Depends(get_db)):
    """Contratos (pncp/transparencia), obras (obrasgov), candidatos (tse), indicadores (ibge),
    finanças estaduais (siconfi), órgãos (camara/transparencia)."""
    stmt = select(Registro).order_by(Registro.ano.desc().nullslast(), Registro.valor.desc().nullslast())
    for col, val in ((Registro.fonte, fonte), (Registro.tipo, tipo), (Registro.ano, ano)):
        if val is not None:
            stmt = stmt.where(col == val)
    if uf:
        stmt = stmt.where(Registro.uf == uf.upper())
    if q:
        stmt = stmt.where(Registro.titulo.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    return {"total": total, "itens": [RegistroOut.model_validate(r) for r in db.scalars(stmt.limit(limit).offset(offset))]}


@router.get("/registros/{rid}", response_model=RegistroOut, tags=["Dados"])
def detalhe_registro(rid: int, db: Session = Depends(get_db)):
    r = db.get(Registro, rid)
    if not r:
        raise HTTPException(404, "Registro não encontrado")
    return r


def _divida_estado(db, uf):
    """Dívida consolidada (DC) e líquida (DCL) do último RGF disponível (SICONFI, Executivo estadual)."""
    ano = db.scalar(select(func.max(Registro.ano)).where(Registro.tipo == "rgf-anexo02-divida", Registro.uf == uf))
    if not ano:
        return None
    linhas = db.scalars(select(Registro).where(Registro.tipo == "rgf-anexo02-divida", Registro.uf == uf,
                                               Registro.ano == ano)).all()
    out = {"ano": ano}
    for conta, nome in (("DividaConsolidada", "consolidada"), ("DividaConsolidadaLiquida", "consolidada_liquida")):
        da_conta = [r for r in linhas if (r.dados or {}).get("cod_conta") == conta]
        # colunas: "SALDO DO EXERCÍCIO ANTERIOR", "Até o 1º Quadrimestre"... — usa o quadrimestre mais recente
        quad = sorted((r for r in da_conta if "Quadrimestre" in ((r.dados or {}).get("coluna") or "")),
                      key=lambda r: r.dados["coluna"])
        if quad:
            out[nome] = {"valor": quad[-1].valor, "referencia": quad[-1].dados["coluna"]}
    return out


def _ultimo(db, tipo, uf):
    r = db.scalars(select(Registro).where(Registro.tipo == tipo, Registro.uf == uf)
                   .order_by(Registro.ano.desc())).first()
    return {"valor": r.valor, "ano": r.ano, "unidade": (r.dados or {}).get("unidade")} if r else None


@router.get("/estados", tags=["Estados"])
def listar_estados():
    return UFS


@router.get("/estados/{uf}/resumo", tags=["Estados"])
def resumo_estado(uf: str, db: Session = Depends(get_db)):
    """Popout de estado (indicadores, bancada, contratos, obras e fluxo federativo)."""
    uf = uf.upper()
    if uf not in UFS:
        raise HTTPException(404, "UF inválida")
    contagem = lambda casa: db.scalar(select(func.count()).select_from(Parlamentar)
                                      .where(Parlamentar.casa == casa, Parlamentar.uf == uf))
    soma = lambda fonte, tipo: db.scalar(select(func.sum(Registro.valor))
                                         .where(Registro.fonte == fonte, Registro.tipo == tipo, Registro.uf == uf))
    return {
        "uf": uf,
        "indicadores": {
            "populacao": _ultimo(db, "indicador:populacao", uf),
            "pib": _ultimo(db, "indicador:pib", uf),
            "pib_per_capita": _ultimo(db, "indicador:pib_per_capita", uf),
        },
        "bancada": {"deputados": contagem("camara"), "senadores": contagem("senado")},
        "divida": _divida_estado(db, uf),
        "contratos_pncp_total": soma("pncp", "contrato"),
        "obras_federais": db.scalar(select(func.count()).select_from(Registro)
                                    .where(Registro.tipo == "obra", Registro.uf == uf)),
        "fluxo_federativo": fluxo_estado(db, uf, ano) if (ano := ultimo_ano_completo(db)) else None,
    }


@router.get("/estados/{uf}/fluxo", tags=["Estados"])
def fluxo_do_estado(uf: str, ano: int | None = None, db: Session = Depends(get_db)):
    """Arrecadado × redistribuído × retornado de um estado, com metodologia e limitações."""
    uf = uf.upper()
    if uf not in UFS:
        raise HTTPException(404, "UF inválida")
    ano = ano or ultimo_ano_completo(db)
    if not ano:
        raise HTTPException(404, "Sem dados de arrecadação. Rode a coleta receita-arrecadacao.")
    return {**fluxo_estado(db, uf, ano), "metodologia": METODOLOGIA}


@router.get("/fluxo-federativo", tags=["Estados"])
def fluxo_todos(ano: int | None = None, db: Session = Depends(get_db)):
    """Ranking dos 27 estados (para o mapa/tabela da tela inicial)."""
    ano = ano or ultimo_ano_completo(db)
    if not ano:
        raise HTTPException(404, "Sem dados de arrecadação. Rode a coleta receita-arrecadacao.")
    estados = sorted((fluxo_estado(db, uf, ano) for uf in UFS),
                     key=lambda e: e["retorno_por_real_arrecadado"] or 0, reverse=True)
    return {"ano": ano, "estados": estados, "metodologia": METODOLOGIA}


@router.get("/historico-estados", tags=["Estados"])
def historico_estados(db: Session = Depends(get_db)):
    """Série por ano de cada estado, para os gráficos em linha: retorno por R$ 1 arrecadado (fluxo federativo) e
    dívida consolidada do governo estadual (SICONFI, RGF Anexo 2, último quadrimestre de cada ano)."""
    anos = [a for (a,) in db.execute(select(Registro.ano).where(Registro.tipo == "arrecadacao_uf").distinct()
                                     .order_by(Registro.ano)).all() if a]
    retorno = {}
    for ano in anos:
        for uf in UFS:
            r = fluxo_estado(db, uf, ano).get("retorno_por_real_arrecadado")
            if r is not None:
                retorno.setdefault(uf, {})[str(ano)] = r
    # dívida: cada RGF traz o saldo do fim do ano anterior e o de cada quadrimestre; um só relatório já dá 4 pontos.
    # Chaves "ano.quadrimestre": "2024.3" = dezembro de 2024, "2025.1" = abril de 2025 (ordenam certo como texto).
    divida = {}
    for r in db.scalars(select(Registro).where(Registro.tipo == "rgf-anexo02-divida")):
        d = r.dados or {}
        col = d.get("coluna") or ""
        if d.get("cod_conta") != "DividaConsolidada" or not r.uf or r.valor is None:
            continue
        q = re.search(r"(\d)º\s*Quadrimestre", col)
        if q:
            chave = f"{r.ano}.{q.group(1)}"
        elif "ANTERIOR" in col.upper():
            chave = f"{r.ano - 1}.3"
        else:
            continue
        divida.setdefault(r.uf, {}).setdefault(chave, r.valor)
    serie = lambda v: {"anos": sorted({a for x in v.values() for a in x}), "estados": v}
    return {"retorno": serie(retorno), "divida": serie(divida),
            "fonte": "Receita Federal, Tesouro Nacional e SICONFI (Tesouro Nacional)",
            "nota": "Valores nominais, sem correção pela inflação. Um ano só aparece depois de coletado."}


# ---------- coletas ----------

@router.get("/coletas", response_model=list[ColetaOut], tags=["Coletas"])
def listar_coletas(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db)):
    return db.scalars(select(Coleta).order_by(Coleta.id.desc()).limit(limit)).all()


@router.get("/coletas/tarefas", tags=["Coletas"])
def listar_tarefas():
    return sorted(TAREFAS)


@router.post("/coletas/{tarefa}", status_code=202, tags=["Coletas"])
def disparar_coleta(tarefa: str, background: BackgroundTasks, params: dict | None = None,
                    x_admin_token: str = Header(...)):
    import secrets
    if settings.somente_leitura:
        raise HTTPException(403, "Esta API é só de leitura. As coletas rodam no agendador.")
    if settings.admin_token in ("", "troque-este-token") or len(settings.admin_token) < 24:
        raise HTTPException(403, "Defina um ADMIN_TOKEN forte (24+ caracteres) no .env para disparar coletas pela API.")
    if not secrets.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        raise HTTPException(401, "Token inválido")
    if tarefa not in TAREFAS:
        raise HTTPException(404, f"Tarefa desconhecida. Use uma de: {sorted(TAREFAS)}")
    from scripts.coletar import converter_params
    background.add_task(TAREFAS[tarefa], **converter_params(params or {}))
    return {"status": "agendada", "tarefa": tarefa}
