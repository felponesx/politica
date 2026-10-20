"""Endpoints da versão 0.3: economia (Banco Central), contadores, agenda do Congresso, atuação parlamentar
e exportação de dados em CSV."""
import csv
import io
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collectors.bcb import SERIES
from app.db import get_db
from app.models import (Candidato, Contrato, Despesa, DevedorPGFN, Municipio, Norma, Obra, Parlamentar, Proposicao,
                        Registro, Votacao)

router = APIRouter()
SEG_ANO = 365 * 24 * 3600


@router.get("/economia", tags=["Economia"])
def economia(nomes: str | None = None, desde: int | None = None, db: Session = Depends(get_db)):
    """Séries do Banco Central: último valor, valor de 12 meses antes e histórico mensal."""
    lista = [n for n in (nomes.split(",") if nomes else SERIES) if n in SERIES]
    desde = desde or 1985  # desde a volta das eleições diretas; o site deixa escolher o período
    out = {}
    for nome in lista:
        regs = db.scalars(select(Registro).where(Registro.tipo == f"serie:{nome}", Registro.ano >= desde)
                          .order_by(Registro.chave)).all()
        if not regs:
            continue
        # séries mensais vêm com data completa; agrupa por mês para o histórico
        por_mes = {}
        for r in regs:
            por_mes[(r.dados or {}).get("data", r.chave)[:7]] = r
        hist = [{"data": k, "valor": r.valor} for k, r in sorted(por_mes.items())]
        ult = hist[-1]
        ano_antes = next((h for h in reversed(hist) if h["data"] <= f"{int(ult['data'][:4]) - 1}{ult['data'][4:]}"), None)
        codigo, desc, unidade, _ = SERIES[nome]
        out[nome] = {"descricao": desc, "unidade": unidade, "codigo_sgs": codigo, "ultimo": ult,
                     "doze_meses_antes": ano_antes, "historico": hist}
    return {"series": out, "fonte": "Banco Central do Brasil — SGS (inclui dados do IBGE: IPCA e PNAD)"}


def _tributos_subnacionais(db):
    """Impostos estaduais e municipais em 12 meses (último ano com estados no SICONFI). Prefeituras que não entregaram
    o relatório entram estimadas pela média por habitante das que entregaram, na mesma UF."""
    from app.models import Municipio
    anos = [a for (a,) in db.execute(select(Registro.ano).where(Registro.tipo == "tributos_ente").distinct()
                                     .order_by(Registro.ano.desc()))]
    for ano in anos:
        regs = db.scalars(select(Registro).where(Registro.tipo == "tributos_ente", Registro.ano == ano)).all()
        est = [r for r in regs if (r.dados or {}).get("esfera") == "E"]
        if len(est) < 20:
            continue
        estadual = sum(r.valor or 0 for r in est) * (27 / len(est))
        mun = {int((r.dados or {}).get("id_ente")): r.valor or 0 for r in regs if (r.dados or {}).get("esfera") == "M"}
        cidades = db.execute(select(Municipio.codigo_ibge, Municipio.uf, Municipio.populacao)).all()
        municipal, faltam = sum(mun.values()), 0
        if cidades and mun:
            pc = {}
            for cod, uf, pop in cidades:
                if int(cod) in mun and pop:
                    a = pc.setdefault(uf, [0.0, 0])
                    a[0] += mun[int(cod)]
                    a[1] += pop
            for cod, uf, pop in cidades:
                if int(cod) not in mun and pop and uf in pc and pc[uf][1]:
                    municipal += pc[uf][0] / pc[uf][1] * pop
                    faltam += 1
        nota = (f"Estados: {len(est)} de 27 relatórios. Municípios: {len(mun)} relatórios"
                + (f"; {faltam} prefeituras sem relatório estimadas pela média por habitante do estado." if faltam else ".")
                if mun else f"Estados: {len(est)} de 27 relatórios. Municípios ainda não coletados (ISS e IPTU fora da conta).")
        return {"estadual": round(estadual, 2), "municipal": round(municipal, 2), "ate": f"12/{ano}", "nota": nota}
    return None


@router.get("/contadores", tags=["Economia"])
def contadores(db: Session = Depends(get_db)):
    """Base real do impostômetro e do gastômetro: valor por segundo calculado com os últimos dados oficiais."""
    hoje = date.today()
    imp = None
    for ano in (hoje.year, hoje.year - 1):
        linhas = db.execute(select(Registro.dados, Registro.valor).where(Registro.tipo == "arrecadacao_uf",
                                                                         Registro.ano == ano)).all()
        if not linhas:
            continue
        total = sum(v or 0 for _, v in linhas)
        meses = max(int((d or {}).get("mes") or 0) for d, _ in linhas)
        segundos = (datetime(ano + (meses == 12), meses % 12 + 1, 1) - datetime(ano, 1, 1)).total_seconds()
        imp = {"por_segundo": round(total / segundos, 2), "base": f"tributos federais arrecadados de janeiro a {meses:02d}/{ano}",
               "total_base": round(total, 2), "ano": ano, "meses": meses,
               "fonte": "Receita Federal (arrecadação federal por estado)",
               "nota": "Só tributos federais: o ICMS dos estados e o ISS e IPTU dos municípios não entram."}
        break
    if imp:
        sub = _tributos_subnacionais(db)
        if sub:
            fed_ano = imp["por_segundo"] * SEG_ANO
            partes = {"federal": round(fed_ano, 2), "estadual": sub["estadual"], "municipal": sub["municipal"]}
            tot = sum(partes.values())
            imp.update({
                "por_segundo": round(tot / SEG_ANO, 2), "partes_ano": partes,
                "partes_pct": {k: round(100 * v / tot, 1) for k, v in partes.items()},
                "base": f"tributos federais (janeiro a {imp['meses']:02d}/{imp['ano']}), estaduais e municipais "
                        f"(12 meses até {sub['ate']})",
                "fonte": "Receita Federal (tributos federais) e SICONFI/Tesouro Nacional, RREO Anexo 03 "
                         "(impostos, taxas e contribuições de melhoria de cada estado e município)",
                "nota": "Federal, estadual e municipal somados, no ritmo dos últimos dados publicados. " + sub["nota"]})
    gas = None
    anos = sorted({a for (a,) in db.execute(select(Registro.ano).where(Registro.tipo == "despesa_funcao").distinct())}, reverse=True)
    for ano in anos:
        regs = db.scalars(select(Registro).where(Registro.tipo == "despesa_funcao", Registro.ano == ano)).all()
        por_esfera = {}
        for r in regs:
            e = (r.dados or {}).get("esfera")
            por_esfera[e] = por_esfera.get(e, 0) + (r.valor or 0)
        if "U" not in por_esfera:
            continue
        total = sum(por_esfera.values())
        por_funcao = {}
        for r in regs:
            por_funcao[r.titulo] = por_funcao.get(r.titulo, 0) + (r.valor or 0)
        top = sorted(por_funcao.items(), key=lambda x: -x[1])[:4]
        gas = {"por_segundo": round(total / SEG_ANO, 2), "ano": ano, "total_base": round(total, 2),
               "por_esfera": {k: round(v, 2) for k, v in por_esfera.items()},
               "maiores_funcoes": [{"funcao": f, "percentual": round(100 * v / total, 1)} for f, v in top],
               "base": f"despesa liquidada em {ano} (União" + (", estados" if "E" in por_esfera else "")
                       + (", capitais" if "C" in por_esfera else "") + (" e municípios" if "M" in por_esfera else "") + ")",
               "fonte": "SICONFI (RREO Anexo 02)"}
        break
    return {"impostometro": imp, "gastometro": gas}


@router.get("/agora/eventos", tags=["Legislativo"])
def eventos(dia: date | None = None, db: Session = Depends(get_db)):
    """Sessões, reuniões de comissão e audiências do dia na Câmara e no Senado."""
    dia = dia or date.today()
    regs = [r for r in db.scalars(select(Registro).where(Registro.tipo == "evento", Registro.ano == dia.year))
            if (r.dados or {}).get("dia") == dia.isoformat()]
    itens = sorted(({"id": r.id, "casa": r.dados.get("casa"), "titulo": r.titulo, "tipo": r.dados.get("tipo"),
                     "inicio": r.dados.get("inicio"), "fim": r.dados.get("fim"), "situacao": r.dados.get("situacao"),
                     "orgaos": r.dados.get("orgaos"), "local": r.dados.get("local"), "pauta": r.dados.get("pauta") or [],
                     "video": r.dados.get("video"),
                     "ao_vivo": "andamento" in str(r.dados.get("situacao") or "").lower()} for r in regs),
                   key=lambda e: (not e["ao_vivo"], e["inicio"] or ""))
    atualizado = max((r.atualizado_em for r in regs), default=None)
    return {"dia": dia, "atualizado_em": atualizado, "itens": itens,
            "fonte": "Câmara dos Deputados (eventos) e Senado Federal (agenda do plenário)"}


@router.get("/parlamentares/{pid}/atuacao", tags=["Legislativo"])
def atuacao(pid: int, db: Session = Depends(get_db)):
    p = db.get(Parlamentar, pid)
    if not p:
        raise HTTPException(404, "Parlamentar não encontrado")
    r = db.scalar(select(Registro).where(Registro.tipo == "atuacao", Registro.chave == str(pid)))
    projetos = [x for x in db.scalars(select(Registro).where(Registro.tipo == "tramitacao"))
                if any(str(a.get("id_externo")) == p.id_externo and (a.get("casa") or "camara") == p.casa
                       for a in (x.dados or {}).get("autores") or [])] if p.casa in ("camara", "senado") else []
    return {"comissoes": (r.dados or {}).get("comissoes", []) if r else [],
            "discursos_12_meses": (r.dados or {}).get("discursos") if r else None,
            "ultimos_discursos": (r.dados or {}).get("ultimos_discursos", []) if r else [],
            "projetos_autoria": [{"proposicao_id": int(x.chave), "titulo": x.titulo} for x in projetos[:50]],
            "atualizado_em": r.atualizado_em if r else None,
            "fonte": "Câmara dos Deputados" if p.casa == "camara" else "Senado Federal"}


# ---------- exportação ----------

def _colunas(modelo, excluir=("registro_id", "normalizado_em", "atualizado_em", "dados")):
    return [c.name for c in modelo.__table__.columns if c.name not in excluir]


CONJUNTOS = {
    "parlamentares": (Parlamentar, "Deputados federais e senadores"),
    "votacoes": (Votacao, "Votações da Câmara e do Senado"),
    "proposicoes": (Proposicao, "Projetos e proposições"),
    "normas": (Norma, "Leis e normas federais e estaduais"),
    "contratos": (Contrato, "Contratos públicos (PNCP e Portal da Transparência)"),
    "obras": (Obra, "Obras federais (ObrasGov)"),
    "municipios": (Municipio, "Municípios (IBGE e CAPAG)"),
    "cota-parlamentar": (Despesa, "Despesas da cota parlamentar (Câmara e Senado)"),
    "devedores-uniao": (DevedorPGFN, "Empresas na dívida ativa da União (PGFN)"),
    "candidatos": (Candidato, "Candidaturas (TSE)"),
}


@router.get("/exportar", tags=["Exportação"])
def conjuntos(db: Session = Depends(get_db)):
    return [{"conjunto": k, "descricao": d, "linhas": db.scalar(select(func.count()).select_from(m)),
             "csv": f"/exportar/{k}.csv"} for k, (m, d) in CONJUNTOS.items()]


@router.get("/exportar/{conjunto}.csv", tags=["Exportação"])
def exportar(conjunto: str, uf: str | None = None, ano: int | None = None, limite: int = Query(200_000, le=1_000_000),
             db: Session = Depends(get_db)):
    """CSV (separado por ponto e vírgula, UTF-8 com BOM, abre direto no Excel)."""
    if conjunto not in CONJUNTOS:
        raise HTTPException(404, f"Conjunto desconhecido. Use: {', '.join(CONJUNTOS)}")
    modelo = CONJUNTOS[conjunto][0]
    cols = _colunas(modelo)
    stmt = select(modelo)
    if uf and "uf" in cols:
        stmt = stmt.where(modelo.uf == uf.upper())
    if ano and "ano" in cols:
        stmt = stmt.where(modelo.ano == ano)
    stmt = stmt.order_by(modelo.id).limit(limite)

    def gerar():
        from app.db import SessionLocal
        sessao = SessionLocal()  # sessão própria: a resposta continua sendo enviada depois que a rota retorna
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        buf.write("﻿")
        w.writerow(cols)
        yield buf.getvalue()
        buf.seek(0), buf.truncate(0)
        try:
            for i, obj in enumerate(sessao.execute(stmt.execution_options(yield_per=2000)).scalars()):
                w.writerow(["" if getattr(obj, c) is None else getattr(obj, c) for c in cols])
                if i % 1000 == 999:
                    yield buf.getvalue()
                    buf.seek(0), buf.truncate(0)
            yield buf.getvalue()
        finally:
            sessao.close()

    nome = f"brasilplus-{conjunto}{'-' + uf.upper() if uf else ''}{'-' + str(ano) if ano else ''}.csv"
    return StreamingResponse(gerar(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{nome}"'})


@router.get("/assembleias", tags=["Legislativo"])
def assembleias(db: Session = Depends(get_db)):
    """Assembleias com dados da própria casa (deputados em exercício e votações)."""
    deps = dict(db.execute(select(Parlamentar.casa, func.count()).where(Parlamentar.casa.like("al-%"), Parlamentar.em_exercicio)
                           .group_by(Parlamentar.casa)).all())
    vots = dict(db.execute(select(Votacao.casa, func.count()).where(Votacao.casa.like("al-%")).group_by(Votacao.casa)).all())
    return {c[3:].upper(): {"deputados": deps.get(c, 0), "votacoes": vots.get(c, 0)} for c in sorted(set(deps) | set(vots))}


# ---------- mapas ----------

@router.get("/malhas/{uf}", tags=["Mapas"])
def malha(uf: str, db: Session = Depends(get_db)):
    """Contorno dos municípios do estado (caminhos SVG já projetados)."""
    r = db.scalar(select(Registro).where(Registro.tipo == "malha", Registro.chave == uf.upper()))
    if not r:
        raise HTTPException(404, "Malha não coletada. Rode ibge-malhas.")
    return {"uf": uf.upper(), **(r.dados or {}), "fonte": "IBGE — malhas municipais"}


@router.get("/mapa/estados", tags=["Mapas"])
def mapa_estados(db: Session = Depends(get_db)):
    """Métricas oficiais por estado para o mapa da tela inicial (só entra o que já foi coletado)."""
    from app.fluxo import fluxo_estado, ultimo_ano_completo
    from app.models import Indicador, Obra
    from app.routers.dados import _divida_estado
    from app.utils import UFS
    est = {uf: {} for uf in UFS}
    for i in db.scalars(select(Indicador).where(Indicador.nome == "populacao").order_by(Indicador.ano)):
        if i.uf in est and i.valor:
            est[i.uf]["pop"] = i.valor
    regs = db.execute(select(Registro.uf, Registro.ano, Registro.valor, Registro.dados).where(Registro.tipo == "despesa_funcao",
                                                                                            Registro.uf.isnot(None))).all()
    por_ano = {}
    for uf, ano, v, d in regs:
        if (d or {}).get("esfera") == "E" and uf in est:
            por_ano.setdefault(ano, {}).setdefault(uf, 0)
            por_ano[ano][uf] += v or 0
    ano_g = max((a for a, m in por_ano.items() if len(m) >= 20), default=max(por_ano, default=None))
    for uf, v in (por_ano.get(ano_g) or {}).items():
        est[uf]["gasto"] = round(v, 2)
        if est[uf].get("pop"):
            est[uf]["pc"] = round(v / est[uf]["pop"], 2)
    for uf, q, v in db.execute(select(Contrato.uf, func.count(), func.sum(Contrato.valor)).group_by(Contrato.uf)):
        if uf in est:
            est[uf]["contratos"], est[uf]["contratos_valor"] = q, round(v or 0, 2)
    for uf, q in db.execute(select(Obra.uf, func.count()).group_by(Obra.uf)):
        if uf in est:
            est[uf]["obras"] = q
    ano_f = ultimo_ano_completo(db)
    if ano_f:
        for uf in UFS:
            f = fluxo_estado(db, uf, ano_f)
            if f["arrecadado"] is not None:
                est[uf]["arr"] = f["arrecadado"]
            if f["retornado"] is not None:
                est[uf]["ret"] = f["retornado"]
    for uf in UFS:
        dv = _divida_estado(db, uf)
        if dv and dv.get("consolidada"):
            est[uf]["divida"] = dv["consolidada"]["valor"]
    disponiveis = {k for e in est.values() for k in e}
    return {"anos": {"gasto": ano_g, "fluxo": ano_f}, "metricas": sorted(disponiveis), "estados": est,
            "fonte": "IBGE, SICONFI, PNCP, Portal da Transparência, ObrasGov, Receita Federal e Tesouro Nacional"}


# ---------- empresas por setor (CNAE) ----------

@router.get("/empresas-setores", tags=["Empresas"])
def empresas_setores(db: Session = Depends(get_db)):
    from app.models import EmpresaCadastro
    from app.setores import SETORES, setor_de_cnae
    cont = {s: 0 for s in SETORES}
    for (cnae,) in db.execute(select(EmpresaCadastro.cnae)):
        cont[setor_de_cnae(cnae)] += 1
    return [{"setor": s, "empresas": n} for s, n in cont.items()]


@router.get("/empresas", tags=["Empresas"])
def empresas(setor: str | None = None, uf: str | None = None, q: str | None = None, limit: int = Query(50, le=200),
             offset: int = 0, db: Session = Depends(get_db)):
    """Fornecedores com cadastro na Receita, com setor (pela CNAE) e o total recebido em contratos públicos."""
    from app.models import EmpresaCadastro
    from app.setores import setor_de_cnae
    from app.utils import formatar_documento
    stmt = select(EmpresaCadastro)
    if uf:
        stmt = stmt.where(EmpresaCadastro.uf == uf.upper())
    if q:
        stmt = stmt.where(EmpresaCadastro.razao_social.ilike(f"%{q}%"))
    lista = [e for e in db.scalars(stmt) if not setor or setor_de_cnae(e.cnae) == setor]
    totais = dict(db.execute(select(Contrato.cnpj_fornecedor, func.sum(Contrato.valor))
                             .where(Contrato.cnpj_fornecedor.in_([e.cnpj for e in lista] or [""]))
                             .group_by(Contrato.cnpj_fornecedor)).all())
    lista.sort(key=lambda e: -(totais.get(e.cnpj) or 0))
    return {"total": len(lista), "itens": [{"cnpj": e.cnpj, "documento": formatar_documento(e.cnpj), "razao_social": e.razao_social,
                                             "nome_fantasia": e.nome_fantasia, "cnae_descricao": e.cnae_descricao,
                                             "setor": setor_de_cnae(e.cnae), "municipio": e.municipio, "uf": e.uf,
                                             "situacao": e.situacao, "socios": len(e.socios or []),
                                             "total_contratos": round(totais.get(e.cnpj) or 0, 2)} for e in lista[offset:offset + limit]]}


AVISO_RJ = ("Lista do cadastro de CNPJ da Receita Federal (campo \"situação especial\"). É o registro da Receita, "
            "não a lista oficial do Judiciário: pode atrasar em relação ao processo, e estar em recuperação judicial "
            "não é irregularidade — é o instrumento legal (Lei 11.101/2005) para a empresa renegociar dívidas.")


def _rj_filtro(tipo, uf, q, situacao):
    filtro = [Registro.fonte == "receita", Registro.tipo == ("falencia" if tipo == "falencia" else "recuperacao_judicial")]
    if uf:
        filtro.append(Registro.uf == uf.upper())
    if q:
        filtro.append(Registro.titulo.ilike(f"%{q}%"))
    return filtro, (situacao or "").strip().lower()


@router.get("/recuperacao-judicial", tags=["Empresas", "Dívidas"])
def recuperacao_judicial(tipo: str = "recuperacao_judicial", uf: str | None = None, q: str | None = None,
                         situacao: str | None = None, ordenar: str = "capital", limit: int = Query(50, le=500),
                         offset: int = 0, db: Session = Depends(get_db)):
    """Empresas em recuperação judicial (ou `tipo=falencia`) segundo a base aberta do CNPJ.
    `situacao`: situação cadastral (Ativa, Baixada, Inapta...). `ordenar`: capital (padrão), data ou nome."""
    from app.utils import formatar_documento
    filtro, sit = _rj_filtro(tipo, uf, q, situacao)
    regs = db.scalars(select(Registro).where(*filtro)).all()
    if sit:
        regs = [r for r in regs if (r.dados or {}).get("situacao_cadastral", "").lower() == sit]
    chave = {"data": lambda r: (r.dados or {}).get("data_situacao_especial") or "",
             "nome": lambda r: r.titulo or ""}.get(ordenar, lambda r: r.valor or 0)
    regs.sort(key=chave, reverse=ordenar != "nome")
    return {"total": len(regs), "aviso": AVISO_RJ,
            "itens": [{**(r.dados or {}), "documento": formatar_documento(r.chave), "nome": r.titulo}
                      for r in regs[offset:offset + limit]]}


@router.get("/recuperacao-judicial/resumo", tags=["Empresas", "Dívidas"])
def recuperacao_judicial_resumo(tipo: str = "recuperacao_judicial", db: Session = Depends(get_db)):
    """Contagens por estado, porte, situação cadastral e ano em que a situação foi registrada."""
    filtro, _ = _rj_filtro(tipo, None, None, None)
    regs = db.scalars(select(Registro).where(*filtro)).all()
    if not regs:
        raise HTTPException(404, "Sem dados. Rode a coleta receita-recuperacao-judicial.")

    def contar(fn):
        out = {}
        for r in regs:
            k = fn(r) or "Não informado"
            out[k] = out.get(k, 0) + 1
        return dict(sorted(out.items(), key=lambda x: -x[1]))
    ativas = [r for r in regs if (r.dados or {}).get("situacao_cadastral") == "Ativa"]
    return {"total": len(regs), "ativas": len(ativas), "capital_social_ativas": round(sum(r.valor or 0 for r in ativas), 2),
            "por_uf": contar(lambda r: r.uf), "por_porte": contar(lambda r: (r.dados or {}).get("porte")),
            "por_situacao_cadastral": contar(lambda r: (r.dados or {}).get("situacao_cadastral")),
            "por_ano": dict(sorted(contar(lambda r: str(r.ano) if r.ano else None).items())),
            "mes_base": next(((r.dados or {}).get("mes_base") for r in regs), None), "aviso": AVISO_RJ,
            "fonte": "Receita Federal — dados abertos do CNPJ"}


# ---------- notícias de política ----------

@router.get("/noticias", tags=["Notícias"])
def noticias(veiculo: str | None = None, q: str | None = None, limit: int = Query(50, le=1500), offset: int = 0,
             db: Session = Depends(get_db)):
    """Últimas matérias de política dos principais veículos (título, resumo, data e link para o original)."""
    from app.utils import sem_acento
    itens = [r.dados or {} for r in db.scalars(select(Registro).where(Registro.fonte == "noticias",
                                                                       Registro.tipo == "materia"))]
    if veiculo:
        itens = [i for i in itens if i.get("veiculo") == veiculo]
    if q:
        termo = sem_acento(q).lower()
        itens = [i for i in itens if termo in sem_acento(f"{i.get('titulo')} {i.get('resumo')}").lower()]
    itens.sort(key=lambda i: i.get("data") or "", reverse=True)
    veiculos = {}
    for r in db.scalars(select(Registro).where(Registro.fonte == "noticias", Registro.tipo == "materia")):
        v = (r.dados or {}).get("veiculo")
        veiculos[v] = veiculos.get(v, 0) + 1
    return {"total": len(itens), "itens": itens[offset:offset + limit], "veiculos": veiculos,
            "aviso": "Títulos e resumos dos feeds públicos de cada veículo; a matéria completa fica no site original."}


class PerguntaWeb(BaseModel):
    pergunta: str = Field(..., min_length=2, max_length=600)


@router.post("/ia/web", tags=["IA"])
def ia_web(corpo: PerguntaWeb):
    """Pesquisa na internet (Perplexity) para a IA do site, quando os dados oficiais não têm a resposta.
    A chave fica só no servidor (PERPLEXITY_API_KEY)."""
    import httpx

    from app import ia_web as web
    try:
        return web.pesquisar(corpo.pergunta)
    except web.SemChave as e:
        raise HTTPException(503, str(e))
    except web.LimiteDiario as e:
        raise HTTPException(429, str(e))
    except (httpx.HTTPError, RuntimeError, ValueError):
        raise HTTPException(502, "A pesquisa na internet falhou agora. Tente de novo daqui a pouco.")


@router.get("/ia/indice", tags=["IA"])
def ia_indice():
    """Índice da IA do site (rankings de gastos da cota, mais votados e mandatos desde 1994).

    O robô o monta junto com a cópia estática (scripts/exportar_snapshot.py); aqui ele é lido de site/dados."""
    import json
    from pathlib import Path

    def fnv1a(texto):  # o mesmo hash da cópia estática (scripts/exportar_snapshot.py)
        h = 0x811C9DC5
        for c in texto:
            h = ((h ^ ord(c)) * 0x01000193) & 0xFFFFFFFF
        return h

    pasta = Path(__file__).resolve().parents[2] / "site" / "dados"
    try:
        n = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))["shards"]
        valor = json.loads((pasta / f"s{fnv1a('/ia/indice') % n}.json").read_text(encoding="utf-8")).get("/ia/indice")
    except (OSError, ValueError, KeyError):
        valor = None
    if not valor:
        raise HTTPException(404, "Índice da IA ainda não gerado: rode python -m scripts.indice_ia (ou o robô de coleta).")
    return valor
