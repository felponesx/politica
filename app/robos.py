"""Robôs do BRASIL+: o que cada coletor está captando, agrupado por categoria, e a auditoria do verificador Gemini.

Status de cada robô (vem do último registro da tabela `coletas`):
  captando  — rodando agora
  ok        — última coleta boa há no máximo 10 dias
  atrasado  — última coleta boa é mais antiga que isso
  parcial   — terminou, mas com falhas em parte das fontes
  falhou    — última execução terminou com erro ou foi abortada
  aguardando— nunca rodou no sistema
Veículos de notícia: ok quando houve matéria nos últimos 7 dias; sem matéria recente caso contrário.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.collectors import TAREFAS
from app.collectors.registro import registro_das_tarefas
from app.models import Coleta, Registro

AVISO = ("Status dos robôs segundo o último registro de cada coleta. 'ok' quer dizer que a última coleta deu certo; "
         "não garante que cada número esteja correto. A auditoria do Gemini aponta suspeitas para conferência humana.")

CATEGORIAS = [
    ("congresso", "Congresso e votações", {"camara", "senado", "congresso", "lexml", "assembleias", "arquivo", "cpis"}),
    ("noticias", "Notícias", {"noticias"}),
    ("saude", "Saúde e ensino", {"saude", "datasus", "inep", "ensino"}),
    ("economia", "Economia, dívidas e arrecadação", {"receita", "tesouro", "siconfi", "bcb", "pgfn", "reforma", "cgibs", "caged"}),
    ("eleicoes", "Eleições", {"tse"}),
    ("seguranca", "Segurança pública", {"fbsp", "sinesp", "sisdepen", "isp-rj", "prf", "defesacivil"}),
    ("obras", "Obras, transporte e energia", {"obrasgov", "anac", "anatel", "anp", "aneel", "osm", "malha", "tomtom", "ibge"}),
    ("ambiente", "Meio ambiente", {"ibama", "inpe", "mapbiomas", "queimadas"}),
    ("transparencia", "Transparência e controle", {"transparencia", "cgu", "tcu", "pncp", "querido_diario", "escandalos", "mte"}),
    ("gemini", "Corretor Gemini", {"gemini"}),
]
OUTRAS = ("outras", "Outras fontes")
ATRASO_DIAS = 10
DIAS_NOTICIA = 7
RODANDO, OK, ATRASADO, PARCIAL, FALHOU, AGUARDANDO = "captando", "ok", "atrasado", "parcial", "falhou", "aguardando"
SEM_MATERIA = "sem_materia"
ROTULOS = {RODANDO: "Captando agora", OK: "Ok", ATRASADO: "Atrasado", PARCIAL: "Parcial", FALHOU: "Falhou", AGUARDANDO: "Aguardando primeira coleta", SEM_MATERIA: "Sem matéria recente"}


def categoria_de(fonte: str) -> tuple[str, str]:
    for slug, nome, fontes in CATEGORIAS:
        if fonte in fontes:
            return slug, nome
    return OUTRAS


def situacao(coleta: Coleta | None, agora: datetime) -> str:
    if coleta is None:
        return AGUARDANDO
    if coleta.status == "rodando":
        return RODANDO
    if coleta.status in ("erro", "abortada"):
        return FALHOU
    if coleta.status == "parcial":
        return PARCIAL
    fim = coleta.fim or coleta.inicio
    if fim and agora - fim > timedelta(days=ATRASO_DIAS):
        return ATRASADO
    return OK


def _ultima_coleta(db, fonte: str, tarefa: str) -> Coleta | None:
    return db.execute(select(Coleta).where(Coleta.fonte == fonte, Coleta.tarefa == tarefa).order_by(Coleta.id.desc()).limit(1)).scalar_one_or_none()


def bots(db, agora: datetime | None = None) -> list[dict]:
    """Um item por tarefa do sistema, com a situação da última execução."""
    agora = agora or datetime.now()
    saida = []
    for nome_tarefa, (fonte, tarefa) in sorted(registro_das_tarefas().items()):
        if nome_tarefa not in TAREFAS:
            continue
        c = _ultima_coleta(db, fonte, tarefa)
        sit = situacao(c, agora)
        slug, nome_cat = categoria_de(fonte)
        saida.append({"tarefa": nome_tarefa, "fonte": fonte, "categoria": slug, "categoria_nome": nome_cat, "situacao": sit,
                      "rotulo": ROTULOS[sit], "ultima_coleta": (c.fim or c.inicio).isoformat(timespec="minutes") if c else None,
                      "itens": c.itens if c else 0, "erro": (c.erro or "")[:300] if c and c.erro else None})
    return saida


def veiculos_noticia(db, agora: datetime | None = None) -> list[dict]:
    """Cada veículo de FEEDS, com a última matéria gravada e a quantidade dos últimos 7 dias."""
    from app.collectors.noticias import FEEDS
    agora = agora or datetime.now()
    limite = agora - timedelta(days=DIAS_NOTICIA)
    ultimo: dict[tuple, datetime] = {}
    recentes: dict[tuple, int] = {}
    for r in db.execute(select(Registro).where(Registro.fonte == "noticias", Registro.tipo == "materia")).scalars():
        d = r.dados or {}
        v = ((d.get("veiculo") or "").strip().lower(), (d.get("tema") or "geral").strip().lower())
        dt = None
        try:
            dt = datetime.fromisoformat(str(d.get("data") or "")[:19])
        except ValueError:
            dt = None
        if not v[0]:
            continue
        if dt and (v not in ultimo or dt > ultimo[v]):
            ultimo[v] = dt
        if dt and dt >= limite:
            recentes[v] = recentes.get(v, 0) + 1
    saida, vistos = [], set()
    for veiculo, _url, _so, tema in FEEDS:
        chave = (veiculo, tema)
        if chave in vistos:
            continue
        vistos.add(chave)
        k = (veiculo.strip().lower(), tema.strip().lower())
        n = recentes.get(k, 0)
        sit = OK if n else SEM_MATERIA
        saida.append({"veiculo": veiculo, "tema": tema, "situacao": sit, "rotulo": ROTULOS[sit],
                      "materias_7_dias": n, "ultima_materia": ultimo[k].isoformat(timespec="minutes") if k in ultimo else None})
    return saida


def resumo(db) -> dict:
    lista = bots(db)
    cats = []
    for slug, nome, *_ in [(c[0], c[1], c[2]) if len(c) == 3 else (c[0], c[1], None) for c in CATEGORIAS + [OUTRAS]]:
        itens = [b for b in lista if b["categoria"] == slug]
        if not itens and slug == OUTRAS[0]:
            continue
        cats.append({"slug": slug, "nome": nome, "bots": len(itens),
                     "captando": sum(b["situacao"] == RODANDO for b in itens),
                     "ok": sum(b["situacao"] == OK for b in itens),
                     "atrasados": sum(b["situacao"] == ATRASADO for b in itens),
                     "falhas": sum(b["situacao"] in (FALHOU, PARCIAL) for b in itens),
                     "aguardando": sum(b["situacao"] == AGUARDANDO for b in itens)})
    return {"aviso": AVISO, "categorias": cats, "total_bots": len(lista)}


def categoria(db, slug: str) -> dict | None:
    nomes = {s: n for s, n, _ in CATEGORIAS}
    nomes[OUTRAS[0]] = OUTRAS[1]
    if slug not in nomes:
        return None
    itens = [b for b in bots(db) if b["categoria"] == slug]
    out = {"aviso": AVISO, "slug": slug, "nome": nomes[slug], "bots": itens}
    if slug == "noticias":
        out["veiculos"] = veiculos_noticia(db)
    return out


def auditoria(db) -> dict:
    """Erros apontados: sugestões do Gemini (banco) e relatos feitos à mão (app/dados/auditoria_manual.json)."""
    itens = []
    for r in db.execute(select(Registro).where(Registro.fonte == "gemini", Registro.tipo == "sugestao").order_by(Registro.id)).scalars():
        d = r.dados or {}
        itens.append({"id": f"gemini-{r.id}", "origem": "Gemini", "arquivo": d.get("arquivo", ""), "problema": d.get("problema", ""),
                      "sugestao": d.get("sugestao", ""), "fonte_citada": d.get("fonte_citada", ""), "confianca": d.get("confianca", ""),
                      "detalhe": "", "status": d.get("status", "pendente")})
    manual = Path(__file__).parent / "dados" / "auditoria_manual.json"
    if manual.exists():
        itens += json.loads(manual.read_text(encoding="utf-8"))
    cont = {"pendente": 0, "aprovada": 0, "descartada": 0}
    for i in itens:
        cont[i.get("status", "pendente")] = cont.get(i.get("status", "pendente"), 0) + 1
    return {"aviso": "Erros apontados pelo Gemini e relatos manuais. São suspeitas: só viram correção depois de conferidas na fonte oficial. Nenhum dado foi alterado.",
            "contagem": cont, "itens": itens}
