"""Leitura tolerante de planilhas oficiais (CSV com ; ou , em UTF-8/Latin-1, e XLSX).

Os órgãos mudam nomes de colunas com frequência; por isso os importadores acham as colunas
por pedaços do nome (sem acento, maiúsculas) em vez de nomes exatos.
"""
import csv
import io
import os
import tempfile
import zipfile

from app import http
from app.utils import sem_acento


def baixar_temp(url: str, nome: str) -> str:
    return http.baixar(url, os.path.join(tempfile.gettempdir(), nome))


def _decodificar(bruto: bytes) -> str:
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return bruto.decode(enc)
        except UnicodeDecodeError:
            continue
    return bruto.decode("latin-1", errors="replace")


def _linhas_csv(texto: str):
    amostra = texto[:5000]
    delim = max((";", ",", "\t", "|"), key=amostra.count)
    leitor = csv.reader(io.StringIO(texto), delimiter=delim)
    linhas = list(leitor)
    # pula linhas de título até achar um cabeçalho com pelo menos 3 colunas preenchidas
    i = next((k for k, l in enumerate(linhas[:30]) if sum(1 for c in l if str(c).strip()) >= 3), 0)
    cab = [str(c).strip() for c in linhas[i]]
    for l in linhas[i + 1:]:
        if any(str(c).strip() for c in l):
            yield dict(zip(cab, l))


def _linhas_xlsx(caminho: str):
    try:
        import openpyxl
    except ImportError as e:
        raise RuntimeError("Para ler XLSX instale o openpyxl (está no requirements.txt).") from e
    wb = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    ws = wb.worksheets[0]
    linhas = ws.iter_rows(values_only=True)
    buf = []
    for l in linhas:
        buf.append(l)
        if sum(1 for c in l if c not in (None, "")) >= 3:
            break
    cab = [str(c).strip() if c is not None else "" for c in buf[-1]]
    for l in linhas:
        if any(c not in (None, "") for c in l):
            yield {cab[k]: ("" if v is None else v) for k, v in enumerate(l) if k < len(cab)}


def ler_tabela(caminho: str):
    """Gera dicionários {coluna: valor} de um CSV, XLSX ou ZIP com um desses dentro."""
    baixo = caminho.lower()
    if baixo.endswith(".zip"):
        with zipfile.ZipFile(caminho) as z:
            for nome in z.namelist():
                if nome.lower().endswith((".csv", ".txt")):
                    yield from _linhas_csv(_decodificar(z.read(nome)))
                elif nome.lower().endswith(".xlsx"):
                    destino = os.path.join(tempfile.gettempdir(), os.path.basename(nome))
                    with open(destino, "wb") as f:
                        f.write(z.read(nome))
                    yield from _linhas_xlsx(destino)
        return
    if baixo.endswith((".xlsx", ".xlsm")):
        yield from _linhas_xlsx(caminho)
        return
    with open(caminho, "rb") as f:
        yield from _linhas_csv(_decodificar(f.read()))


def achar_coluna(cabecalho, *pedacos, evitar=()):
    """Primeira coluna cujo nome (sem acento) contém todos os pedaços de algum dos grupos.
    Cada argumento pode ser 'TEXTO' ou ('TEXTO1', 'TEXTO2')."""
    norm = {c: sem_acento(c).replace("_", " ") for c in cabecalho}
    for grupo in pedacos:
        grupo = (grupo,) if isinstance(grupo, str) else grupo
        for c, n in norm.items():
            if all(p in n for p in grupo) and not any(e in n for e in evitar):
                return c
    return None
