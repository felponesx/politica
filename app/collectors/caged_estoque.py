"""Estoque de referência do Novo CAGED por município e subclasse da CNAE (Ministério do Trabalho e Emprego).

Todo ano, depois da RAIS, o MTE atualiza o estoque de vínculos formais ativos sobre o qual o Novo CAGED soma os saldos mensais. O arquivo
`.../estatisticas-trabalho/estoque-de-referencia/estoque-de-referencia-AAAA.zip` (a página `comunicados/comunicado-estoque-de-referencia-de-AAAA` diz a competência
e o total) traz `codmun;cnae20subclas;estoqueref`. Conferido com o arquivo de 2026: 668.902 linhas, 5.570 municípios + "ignorado" (999999), soma = 47.110.663 vínculos =
total do comunicado (dezembro/2025). O servidor responde HEAD com uma página; só o GET devolve o zip. Isto é o ESTOQUE DE REFERÊNCIA ANUAL, não um estoque mensal observado."""
import csv
import hashlib
import io
import logging
import re
import tempfile
import zipfile
from datetime import date
from pathlib import Path

from sqlalchemy.dialects import postgresql, sqlite

from app import http
from app.collectors.base import registrar_coleta
from app.models import CagedEstoqueRef, Registro
from app.utils import upsert

log = logging.getLogger("brasilplus.caged_estoque")
BASE = "https://www.gov.br/trabalho-e-emprego/pt-br/acesso-a-informacao/acoes-e-programas/programas-projetos-acoes-obras-e-atividades/estatisticas-trabalho"
COMUNICADO = BASE + "/comunicados/comunicado-estoque-de-referencia-de-{ano}"
ARQUIVO = BASE + "/estoque-de-referencia/estoque-de-referencia-{ano}.zip"
MINIMO_LINHAS = 400_000
MESES = {"janeiro": 1, "fevereiro": 2, "março": 3, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}


def ler_comunicado(texto_html: str, ano: int) -> dict:
    """Competência e total oficial citados no comunicado ("estoque de referência do Novo Caged em dezembro de 2025 foi atualizado para 47.110.663 vínculos")."""
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", texto_html))
    m = re.search(r"estoque de refer[eê]ncia do Novo Caged em (\w+) de (\d{4}) foi atualizado para ([\d.]+) v[ií]nculos", txt, re.I)
    if not m:
        return {"competencia": f"{ano - 1}-12", "total_oficial": None, "fonte_texto": False}
    return {"competencia": f"{m.group(2)}-{MESES.get(m.group(1).lower(), 12):02d}", "total_oficial": int(m.group(3).replace(".", "")), "fonte_texto": True}


def linhas(zf: zipfile.ZipFile):
    nome = next(n for n in zf.namelist() if n.lower().endswith((".txt", ".csv")))
    leitor = csv.reader(io.TextIOWrapper(zf.open(nome), encoding="utf-8-sig", newline=""), delimiter=";")
    cab = [c.strip().lower() for c in next(leitor)]
    try:
        i = (cab.index("codmun"), cab.index("cnae20subclas"), cab.index("estoqueref"))
    except ValueError:
        raise ValueError(f"Arquivo do estoque de referência mudou: colunas {cab}") from None
    for l in leitor:
        if len(l) <= max(i):
            continue
        try:
            yield l[i[0]].strip().zfill(6), l[i[1]].strip().zfill(7), int(l[i[2]])
        except ValueError:
            continue


def _upsert_lote(db, lote: list[dict]):
    d = db.get_bind().dialect.name
    ins = (postgresql if d == "postgresql" else sqlite).insert(CagedEstoqueRef).values(lote)
    db.execute(ins.on_conflict_do_update(index_elements=["competencia", "cod_municipio", "subclasse"], set_={"vinculos": ins.excluded.vinculos}))


def coletar_caged_estoque(ano: int = 0):
    """Baixa o estoque de referência do ano (padrão: o ano corrente; se ainda não saiu, o anterior), confere o zip e o total do comunicado e grava por município × subclasse."""
    with registrar_coleta("caged", "estoque_referencia", ano=ano or "auto") as (db, n):
        anos = [int(ano)] if ano else [date.today().year, date.today().year - 1]
        arq = escolhido = None
        for a in anos:
            destino = Path(tempfile.mkdtemp(prefix="caged-est-")) / f"estoque-{a}.zip"
            try:
                http.baixar(ARQUIVO.format(ano=a), str(destino))
                if zipfile.is_zipfile(destino):
                    arq, escolhido = destino, a
                    break
            except Exception as e:  # noqa: BLE001
                log.info("estoque de referência %s: %s", a, type(e).__name__)
        if arq is None:
            raise RuntimeError(f"CAGED: estoque de referência não encontrado para {anos}")
        info = {"competencia": f"{escolhido - 1}-12", "total_oficial": None}
        try:
            info = ler_comunicado(http.get(COMUNICADO.format(ano=escolhido), headers={"Accept": "*/*"}, timeout=60).text, escolhido)
        except Exception as e:  # noqa: BLE001
            n.avisos.append(f"comunicado: {type(e).__name__}")
        impressao = hashlib.sha256(arq.read_bytes()).hexdigest()
        total = nlin = 0
        lote: list[dict] = []
        with zipfile.ZipFile(arq) as z:
            if z.testzip() is not None:
                raise RuntimeError("CAGED: zip do estoque de referência corrompido")
            for mun, sub, v in linhas(z):
                lote.append({"competencia": info["competencia"], "cod_municipio": mun, "subclasse": sub, "vinculos": v})
                total += v
                nlin += 1
                if len(lote) >= 5000:
                    _upsert_lote(db, lote)
                    lote = []
            if lote:
                _upsert_lote(db, lote)
        if nlin < MINIMO_LINHAS:
            db.rollback()
            raise RuntimeError(f"CAGED: só {nlin:,} linhas no estoque de referência (esperado ≥ {MINIMO_LINHAS:,}); nada foi gravado")
        conferido = info["total_oficial"] is None or info["total_oficial"] == total
        if not conferido:
            n.avisos.append(f"total {total:,} difere do comunicado ({info['total_oficial']:,})")
        upsert(db, Registro, {"fonte": "caged", "tipo": "estoque_ref_resumo", "chave": info["competencia"]},
               {"ano": escolhido, "titulo": f"Estoque de referência do Novo CAGED ({info['competencia']})", "valor": float(total),
                "dados": {"competencia": info["competencia"], "linhas": nlin, "total_vinculos": total, "total_oficial": info["total_oficial"], "confere_com_comunicado": conferido,
                          "sha256": impressao, "arquivo": ARQUIVO.format(ano=escolhido), "comunicado": COMUNICADO.format(ano=escolhido)}})
        db.commit()
        n += nlin
        arq.unlink(missing_ok=True)
    return n.itens
