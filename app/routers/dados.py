import re
from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request
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


@router.get("/fontes/status", tags=["Coletas"])
def status_das_fontes(db: Session = Depends(get_db)):
    """Saúde de cada fonte: última coleta boa, idade dos dados, última situação e erro recente (resumido, sem detalhes internos).
    Fonte que nunca rodou aparece como "nunca_coletada" (configurada, mas não verificada)."""
    from datetime import datetime
    agora = datetime.now()
    linhas = db.execute(select(Coleta.tarefa, Coleta.status, Coleta.fim, Coleta.inicio, Coleta.itens, Coleta.erro)
                        .order_by(Coleta.id.desc()).limit(5000)).all()
    por: dict[str, dict] = {}
    for tarefa, status, fim, inicio, itens, erro in linhas:  # da mais nova para a mais velha
        d = por.setdefault(tarefa, {"tarefa": tarefa, "ultima_ok": None, "ultimo_status": status, "ultimo_erro": None, "falhas_recentes": 0})
        if d["ultimo_erro"] is None and erro and status in ("erro", "parcial", "abortada"):
            d["ultimo_erro"] = " ".join(erro.split())[:160]
        if status in ("erro", "abortada") and d["ultima_ok"] is None:
            d["falhas_recentes"] += 1
        if status in ("ok", "parcial") and d["ultima_ok"] is None:
            d["ultima_ok"] = (fim or inicio).isoformat(timespec="minutes") if (fim or inicio) else None
            d["itens_ultima_ok"] = itens
            d["horas_desde_ok"] = round((agora - (fim or inicio)).total_seconds() / 3600, 1) if (fim or inicio) else None
    out = []
    for t in sorted(TAREFAS):
        d = por.get(t) or {"tarefa": t, "ultima_ok": None, "ultimo_status": "nunca_coletada", "ultimo_erro": None, "falhas_recentes": 0}
        d["situacao"] = ("nunca_coletada" if d["ultimo_status"] == "nunca_coletada" else "sem_coleta_boa" if d["ultima_ok"] is None
                         else "falhando" if d["ultimo_status"] in ("erro", "abortada") else "ok")
        out.append(d)
    return {"fontes": out, "resumo": {k: sum(1 for d in out if d["situacao"] == k) for k in ("ok", "falhando", "sem_coleta_boa", "nunca_coletada")},
            "aviso": "Mostra se a coleta rodou, não se o número publicado está certo. Dados históricos são mantidos quando uma fonte falha."}


@router.get("/coletas/tarefas", tags=["Coletas"])
def listar_tarefas():
    return sorted(TAREFAS)


def _arquivo_permitido(caminho: str) -> bool:
    from pathlib import Path
    base = Path(settings.pasta_arquivos_coleta).resolve()
    try:
        return Path(caminho).resolve().is_relative_to(base)
    except (OSError, ValueError):
        return False


@router.post("/coletas/{tarefa}", status_code=202, tags=["Coletas"])
def disparar_coleta(tarefa: str, request: Request, background: BackgroundTasks, params: dict | None = None,
                    x_admin_token: str = Header(...)):
    import secrets

    from app import limites
    from app.seguranca import ip_cliente
    if settings.somente_leitura:
        raise HTTPException(403, "Esta API é só de leitura. As coletas rodam no agendador.")
    if settings.admin_token in ("", "troque-este-token") or len(settings.admin_token) < 24:
        raise HTTPException(403, "Defina um ADMIN_TOKEN forte (24+ caracteres) no .env para disparar coletas pela API.")
    try:  # tentativas de adivinhar o token: no máximo 10 por minuto por IP (compartilhado entre processos)
        if not limites.consumir(f"admin:{ip_cliente(request)}", 10, 60).ok:
            raise HTTPException(429, "Muitas tentativas. Espere um minuto.", headers={"Retry-After": "60"})
    except limites.LimiteIndisponivel:
        raise HTTPException(503, "Controle de acesso indisponível.")
    if not secrets.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        raise HTTPException(401, "Token inválido")
    if tarefa not in TAREFAS:
        raise HTTPException(404, f"Tarefa desconhecida. Use uma de: {sorted(TAREFAS)}")
    from scripts.coletar import converter_params
    params = dict(params or {})
    for k in ("arquivo_local", "pasta_local", "arquivo"):  # arquivos só de dentro da pasta de coleta (nada de /etc/passwd)
        if params.get(k) is not None and not _arquivo_permitido(str(params[k])):
            raise HTTPException(422, f"'{k}' fora da pasta permitida ({settings.pasta_arquivos_coleta}).")
    background.add_task(TAREFAS[tarefa], **converter_params(params))
    return {"status": "agendada", "tarefa": tarefa}
