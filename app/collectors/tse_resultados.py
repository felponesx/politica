"""Resultados das eleições — TSE, arquivo "Votação nominal por município e zona".
URL: https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_{ano}.zip
(um CSV por UF, latin-1, separador ';'). Cada linha = candidato × município × zona × turno.
O arquivo _BR traz o Presidente com os votos de todos os estados (SG_UF = estado do município).

Aqui agregamos em memória: total por candidato/turno e, para cargos majoritários, total por município.
O total do Presidente fica com uf "BR"; o resultado em cada estado sai dos votos por município.
"""
import csv
import io
import os
import tempfile
from collections import defaultdict

from sqlalchemy import delete

from app import http
from app.collectors.base import registrar_coleta
from app.collectors.tse import sq_unico
from app.models import ResultadoEleicao, VotoMunicipio
from app.utils import sem_acento

URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/votacao_candidato_munzona/votacao_candidato_munzona_{ano}.zip"
MAJORITARIOS = {"PRESIDENTE", "GOVERNADOR", "SENADOR", "PREFEITO"}
CAMPOS = {"SQ_CANDIDATO", "NR_TURNO", "DS_CARGO", "QT_VOTOS_NOMINAIS_VALIDOS", "QT_VOTOS_NOMINAIS", "DS_SIT_TOT_TURNO",
          "SG_UF", "SG_UE", "NM_UE", "NR_CANDIDATO", "NM_URNA_CANDIDATO", "NM_CANDIDATO", "SG_PARTIDO", "CD_MUNICIPIO", "NM_MUNICIPIO"}


def _int(v) -> int:
    try:
        return int(str(v).strip() or 0)
    except ValueError:
        return 0


def agregar(linhas, ano=None):
    """Recebe dicts do CSV e devolve (candidatos, municipios)."""
    cand = {}
    mun = defaultdict(int)
    for l in linhas:
        sq = sq_unico(l.get("SQ_CANDIDATO"), l.get("SG_UE"), ano)
        if not sq:
            continue
        turno = _int(l.get("NR_TURNO")) or 1
        cargo = sem_acento(l.get("DS_CARGO") or "")
        votos = _int(l.get("QT_VOTOS_NOMINAIS_VALIDOS") or l.get("QT_VOTOS_NOMINAIS"))
        uf = (l.get("SG_UF") or "")[:2]
        chave = (turno, sq)
        if chave not in cand:
            situacao = (l.get("DS_SIT_TOT_TURNO") or "").strip()
            cand[chave] = {
                "turno": turno, "sq_candidato": sq, "uf": "BR" if cargo == "PRESIDENTE" else uf,
                "unidade": l.get("NM_UE"), "cargo": cargo, "numero": l.get("NR_CANDIDATO"),
                "nome": l.get("NM_URNA_CANDIDATO") or l.get("NM_CANDIDATO") or "",
                "partido": l.get("SG_PARTIDO"), "situacao": situacao,
                "eleito": sem_acento(situacao).startswith("ELEITO"), "votos": 0,
            }
        cand[chave]["votos"] += votos
        if cargo in MAJORITARIOS:
            mun[(turno, sq, l.get("CD_MUNICIPIO"), l.get("NM_MUNICIPIO"), cargo, uf)] += votos
    return cand, mun


def coletar_resultados(ano: int, uf: str | None = None, arquivo_local: str | None = None):
    with registrar_coleta("tse", "resultados", ano=ano, uf=uf or "todas") as (db, n):
        import zipfile
        caminho = arquivo_local or http.baixar(URL.format(ano=ano),
                                               os.path.join(tempfile.gettempdir(), f"munzona_{ano}.zip"))
        with zipfile.ZipFile(caminho) as z:
            nomes = [m for m in z.namelist() if m.lower().endswith(".csv")]
            # o arquivo _BRASIL repete os dados das UFs; usamos só os por UF (e o _BR/_ZZ do exterior, se houver)
            nomes = [m for m in nomes if "brasil" not in m.lower()]
            if uf:
                nomes = [m for m in nomes if m.upper().endswith(f"_{uf.upper()}.CSV")]
            # Presidente: desde 2018 vem só no arquivo _BR; antes, cada UF traz os votos do Presidente no estado.
            # Somamos o total de todos os arquivos e gravamos no fim (numa coleta de uma UF só, o total não muda).
            presidente = {}
            for nome in nomes:
                with z.open(nome) as bruto:
                    leitor = csv.reader(io.TextIOWrapper(bruto, encoding="latin-1"), delimiter=";")
                    cab = next(leitor, [])
                    pos = [(c, i) for i, c in enumerate(cab) if c in CAMPOS]
                    # só as colunas usadas (o arquivo de 2022 tem dezenas de milhões de linhas e ~50 colunas)
                    cand, mun = agregar(({c: l[i] for c, i in pos} for l in leitor if len(l) >= len(cab)), ano)
                for k, c in [(k, c) for k, c in cand.items() if c["cargo"] == "PRESIDENTE"]:
                    del cand[k]
                    if k in presidente:
                        presidente[k]["votos"] += c["votos"]
                    else:
                        presidente[k] = dict(c)
                # recarga idempotente: apaga o que havia daquele ano para os pares (UF, cargo) do arquivo e grava
                # de novo. Por par, e não só por UF: o arquivo _BR (Presidente) tem votos de todos os estados e
                # não pode apagar os governadores e deputados que vieram dos arquivos de cada UF.
                # (o Presidente sai de qualquer UF: coletas antigas o gravavam com a UF da primeira linha)
                for uf_c, cargo in {(c["uf"], c["cargo"]) for c in cand.values()}:
                    db.execute(delete(ResultadoEleicao).where(ResultadoEleicao.ano == ano, ResultadoEleicao.cargo == cargo,
                                                              ResultadoEleicao.uf == uf_c))
                for uf_m, cargo in {(k[5], k[4]) for k in mun}:
                    db.execute(delete(VotoMunicipio).where(VotoMunicipio.ano == ano, VotoMunicipio.uf == uf_m,
                                                           VotoMunicipio.cargo == cargo))
                db.bulk_insert_mappings(ResultadoEleicao, [{"ano": ano, **c} for c in cand.values()])
                db.bulk_insert_mappings(VotoMunicipio, [
                    {"ano": ano, "turno": t, "sq_candidato": sq, "cd_municipio": str(cd), "municipio": nm,
                     "cargo": cargo, "uf": u, "votos": v}
                    for (t, sq, cd, nm, cargo, u), v in mun.items()])
                db.commit()
                n += len(cand)
            if presidente and not uf:
                # (coletas antigas gravavam o Presidente com a UF da primeira linha: apaga de qualquer UF)
                db.execute(delete(ResultadoEleicao).where(ResultadoEleicao.ano == ano, ResultadoEleicao.cargo == "PRESIDENTE"))
                db.bulk_insert_mappings(ResultadoEleicao, [{"ano": ano, **c} for c in presidente.values()])
                db.commit()
                n += len(presidente)
    return n.itens
