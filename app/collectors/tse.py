"""Candidatos — Portal de Dados Abertos do TSE (arquivos CSV zipados).
Fonte: https://dadosabertos.tse.jus.br/dataset/?groups=candidatos
"""
import csv
import io
import os
import tempfile
import zipfile

from app import http
from app.collectors.base import registrar_coleta
from app.models import Registro
from app.utils import sem_acento, upsert

URL = "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_{ano}.zip"
CAMPOS = ["ANO_ELEICAO", "SQ_CANDIDATO", "NR_CANDIDATO", "NM_CANDIDATO", "NM_URNA_CANDIDATO",
          "SG_PARTIDO", "SG_UF", "NM_UE", "DS_CARGO", "DS_SITUACAO_CANDIDATURA",
          "DS_SIT_TOT_TURNO", "DS_GRAU_INSTRUCAO", "DS_OCUPACAO", "DS_GENERO", "DS_COR_RACA"]


def coletar_candidatos(ano: int, uf: str | None = None, arquivo_local: str | None = None, apenas_eleitos: bool = False):
    """Baixa (~centenas de MB) e importa. Use `uf` para importar só um estado e `apenas_eleitos=true` para
    guardar só quem foi eleito (em 2024 são ~460 mil candidaturas e ~64 mil eleitos)."""
    with registrar_coleta("tse", "candidatos", ano=ano, uf=uf or "todas", apenas_eleitos=apenas_eleitos) as (db, n):
        caminho = arquivo_local or http.baixar(URL.format(ano=ano), os.path.join(tempfile.gettempdir(), f"cand_{ano}.zip"))
        with zipfile.ZipFile(caminho) as z:
            nomes = [m for m in z.namelist() if m.lower().endswith(".csv") and "brasil" not in m.lower()]
            if uf:
                nomes = [m for m in nomes if m.upper().endswith(f"_{uf.upper()}.CSV")]
            for nome in nomes:
                with z.open(nome) as bruto:
                    leitor = csv.DictReader(io.TextIOWrapper(bruto, encoding="latin-1"), delimiter=";")
                    for linha in leitor:
                        sq = linha.get("SQ_CANDIDATO")
                        if not sq:
                            continue
                        if apenas_eleitos and not sem_acento(linha.get("DS_SIT_TOT_TURNO") or "").startswith("ELEITO"):
                            continue
                        upsert(db, Registro, {"fonte": "tse", "tipo": "candidato", "chave": f"{ano}-{sq}"}, {
                            "uf": (linha.get("SG_UF") or "")[:2] or None, "ano": ano,
                            "titulo": linha.get("NM_URNA_CANDIDATO"),
                            "dados": {k: linha.get(k) for k in CAMPOS},
                        })
                        n += 1
                        if n.itens % 2000 == 0:
                            db.commit()
                db.commit()
    return n.itens
