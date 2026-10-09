"""Assembleias Legislativas: deputados estaduais em exercício e votações.

Não existe API única para as 27 casas, então cada Assembleia tem um adaptador próprio. Os deputados e votos entram nas
mesmas tabelas da Câmara e do Senado, com casa = "al-xx" (ex.: "al-mg"), e por isso aparecem nos mesmos endpoints:
  GET /parlamentares?casa=al-mg · GET /votacoes?casa=al-sp · GET /votacoes/{id}

Adaptadores prontos (a validar na primeira coleta):
- MG: API da ALMG (dadosabertos.almg.gov.br/ws), JSON — deputados em exercício e reuniões de plenário (votos nominais,
  quando a reunião os traz).
- SP: arquivos XML da Alesp (al.sp.gov.br/dados-abertos) — deputados e votações nas comissões permanentes.
Para as demais Assembleias: `assembleia-arquivo uf=XX arquivo=deputados.csv` importa uma planilha publicada pela casa
(colunas nome, partido e, se houver, e-mail, foto e situação). Para criar um adaptador novo, siga o modelo de MG.
"""
import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta

from app import http
from app.collectors.arquivos import achar_coluna, ler_tabela
from app.collectors.base import registrar_coleta
from app.config import settings
from app.models import Parlamentar, Votacao, Voto
from app.utils import hash_curto, para_data, pegar, sem_acento, upsert

log = logging.getLogger("brasilplus.assembleias")


def casa_de(uf: str) -> str:
    return f"al-{uf.lower()}"


def _salvar_deputado(db, uf, id_externo, nome, partido=None, foto=None, email=None, em_exercicio=True):
    if not nome:
        return None
    return upsert(db, Parlamentar, {"casa": casa_de(uf), "id_externo": str(id_externo or hash_curto(uf, nome))[:40]},
                  {"nome": nome.strip()[:200], "partido": (partido or "").strip().upper()[:30] or None, "uf": uf,
                   "foto_url": foto, "email": email, "em_exercicio": em_exercicio})


def _listas(d, chaves):
    """Todas as listas de dicts que tenham alguma das chaves (busca recursiva)."""
    achadas = []
    if isinstance(d, list):
        if d and isinstance(d[0], dict) and any(k in d[0] for k in chaves):
            achadas.append(d)
        for x in d:
            achadas += _listas(x, chaves)
    elif isinstance(d, dict):
        for v in d.values():
            achadas += _listas(v, chaves)
    return achadas


VOTO_NORMAL = {"SIM": "Sim", "NAO": "Não", "ABSTENCAO": "Abstenção", "OBSTRUCAO": "Obstrução", "FAVORAVEL": "Sim",
               "CONTRARIO": "Não", "CONTRA": "Não", "BRANCO": "Abstenção"}


def normalizar_voto(v) -> str:
    s = sem_acento(v or "")
    return next((n for k, n in VOTO_NORMAL.items() if s.startswith(k)), (str(v or "").strip().capitalize() or "Não informado"))


# ---------- Minas Gerais (ALMG) ----------

def mg_deputados(db, n):
    base = settings.almg_url
    resp = http.get_json(f"{base}/deputados/em_exercicio", params={"formato": "json"}) or {}
    for d in next(iter(_listas(resp, ("nome", "id"))), []):
        if _salvar_deputado(db, "MG", pegar(d, "id"), pegar(d, "nome", "nomeParlamentar"), pegar(d, "partido", "siglaPartido"),
                            pegar(d, "urlFoto", "foto"), pegar(d, "email")):
            n += 1


def mg_votacoes(db, n, inicio: date, fim: date):
    base = settings.almg_url
    resp = http.get_json(f"{base}/plenario/reunioes/pesquisa",
                         params={"ini": f"{inicio:%Y%m%d}", "fim": f"{fim:%Y%m%d}", "formato": "json", "tp": 100}) or {}
    deps = {sem_acento(p.nome): p for p in db.query(Parlamentar).filter_by(casa="al-mg")}
    for r in next(iter(_listas(resp, ("dataReuniao", "data", "numero", "horario"))), []):
        dt = para_data(pegar(r, "dataReuniao", "data"))
        hora = str(pegar(r, "horario", "hora") or "14:00")[:5]
        if not dt:
            continue
        try:
            reg = http.get_json(f"{base}/plenario/reunioes/{dt:%Y/%m/%d}/{hora}", params={"formato": "json"}) or {}
        except Exception as e:
            log.info("ALMG reunião %s %s: %s", dt, hora, e)
            continue
        for k, lista in enumerate(_listas(reg, ("voto", "tipoVoto", "descricaoVoto"))):
            v = upsert(db, Votacao, {"casa": "al-mg", "id_externo": f"{dt:%Y%m%d}-{hora}-{k}"},
                       {"data": dt, "orgao": "Plenário ALMG", "descricao": pegar(reg, "descricao", "titulo") or "Votação em plenário",
                        "materia": None, "resultado": None})
            db.flush()
            for item in lista:
                nome = pegar(item, "nome", "deputado", "nomeDeputado")
                if isinstance(nome, dict):
                    nome = pegar(nome, "nome")
                p = deps.get(sem_acento(nome or ""))
                if not p:
                    continue
                upsert(db, Voto, {"votacao_id": v.id, "parlamentar_id": p.id},
                       {"voto": normalizar_voto(pegar(item, "voto", "tipoVoto", "descricaoVoto")), "partido_na_data": p.partido})
                n += 1


# ---------- São Paulo (Alesp) ----------

def _xml_registros(url: str):
    """Baixa o XML da Alesp e gera dicts {campo: texto} de cada registro (filhos diretos da raiz)."""
    texto = http.get(url, headers={"Accept": "application/xml"}).content
    raiz = ET.fromstring(texto)
    for el in raiz:
        d = {c.tag.rsplit("}", 1)[-1]: (c.text or "").strip() for c in el}
        if d:
            yield d


def _campo(d, *pedacos):
    norm = {sem_acento(k): k for k in d}
    for p in pedacos:
        for nk, k in norm.items():
            if p in nk and d[k]:
                return d[k]
    return None


def sp_deputados(db, n):
    for d in _xml_registros(settings.alesp_deputados_url):
        sit = sem_acento(_campo(d, "SITUACAO") or "EXERCICIO")
        if _salvar_deputado(db, "SP", _campo(d, "IDDEPUTADO", "IDSPL", "MATRICULA", "ID"), _campo(d, "NOMEPARLAMENTAR", "NOME"),
                            _campo(d, "PARTIDO", "SIGLA"), _campo(d, "FOTO", "IMAGEM"), _campo(d, "EMAIL"),
                            em_exercicio=(sit.startswith("EXE") or "EXERCICIO" in sit or sit in ("", "ATIVO", "TITULAR")) and "EXERCEU" not in sit):
            n += 1


def sp_votacoes(db, n, inicio: date, fim: date):
    deps = {p.id_externo: p for p in db.query(Parlamentar).filter_by(casa="al-sp")}
    por_nome = {sem_acento(p.nome): p for p in deps.values()}
    for d in _xml_registros(settings.alesp_votacoes_url):
        dt = para_data(_campo(d, "DATA"))
        if dt and not (inicio <= dt <= fim):
            continue
        chave = _campo(d, "IDDELIBERACAO", "IDREUNIAO", "IDDOCUMENTO") or hash_curto(d.get("Data"), _campo(d, "COMISSAO"))
        p = deps.get(_campo(d, "IDDEPUTADO") or "") or por_nome.get(sem_acento(_campo(d, "NOMEDEPUTADO", "DEPUTADO") or ""))
        v = upsert(db, Votacao, {"casa": "al-sp", "id_externo": str(chave)[:60]},
                   {"data": dt, "orgao": (_campo(d, "SIGLACOMISSAO", "COMISSAO") or "Comissão Alesp")[:40],
                    "descricao": _campo(d, "DESCRICAO", "DELIBERACAO", "EMENTA") or "Votação em comissão",
                    "materia": _campo(d, "NUMERODOCUMENTO", "DOCUMENTO", "PROPOSITURA"), "resultado": _campo(d, "RESULTADO")})
        db.flush()
        if p:
            upsert(db, Voto, {"votacao_id": v.id, "parlamentar_id": p.id},
                   {"voto": normalizar_voto(_campo(d, "VOTO")), "partido_na_data": p.partido})
        n += 1


ADAPTADORES = {"MG": (mg_deputados, mg_votacoes), "SP": (sp_deputados, sp_votacoes)}


def coletar_assembleias(ufs: list[str] | None = None, inicio: date | None = None, fim: date | None = None,
                        com_votacoes: bool = True):
    fim = fim or date.today()
    inicio = inicio or fim - timedelta(days=30)
    with registrar_coleta("assembleias", "deputados_votacoes", ufs=",".join(ufs or ADAPTADORES)) as (db, n):
        falhas = []
        for uf in [u.upper() for u in (ufs or ADAPTADORES)]:
            if uf not in ADAPTADORES:
                falhas.append(f"{uf}: sem adaptador (use assembleia-arquivo)")
                continue
            deps, votos = ADAPTADORES[uf]
            try:
                deps(db, n)
                db.commit()
                if com_votacoes:
                    votos(db, n, inicio, fim)
                    db.commit()
            except Exception as e:
                db.rollback()
                falhas.append(f"{uf}: {type(e).__name__}: {e}")
                log.warning("Assembleia %s falhou: %s", uf, e)
        if falhas and not n.itens:
            raise RuntimeError("; ".join(falhas))
        n.avisos += falhas
    return n.itens


def importar_deputados_arquivo(uf: str, arquivo: str):
    """Planilha de deputados estaduais publicada pela Assembleia (CSV ou XLSX)."""
    uf = uf.upper()
    with registrar_coleta("assembleias", "deputados_arquivo", uf=uf, arquivo=arquivo) as (db, n):
        linhas = ler_tabela(arquivo)
        primeira = next(linhas, None)
        if not primeira:
            raise ValueError("Planilha vazia")
        cab = list(primeira)
        c = {"nome": achar_coluna(cab, ("NOME", "PARLAMENTAR"), "NOME"), "partido": achar_coluna(cab, "PARTIDO", "SIGLA"),
             "email": achar_coluna(cab, "MAIL"), "foto": achar_coluna(cab, "FOTO"), "sit": achar_coluna(cab, "SITUACAO"),
             "id": achar_coluna(cab, ("ID",), "CODIGO", "MATRICULA", evitar=("PARTIDO",))}
        if not c["nome"]:
            raise ValueError(f"Não achei a coluna de nome. Cabeçalho: {cab[:10]}")
        for l in [primeira, *linhas]:
            g = lambda k: str(l.get(c[k]) or "").strip() if c[k] else ""
            sit = sem_acento(g("sit"))
            if _salvar_deputado(db, uf, g("id") or None, g("nome"), g("partido"), g("foto") or None, g("email") or None,
                                em_exercicio=not sit or "EXERC" in sit or sit == "ATIVO"):
                n += 1
    return n.itens
