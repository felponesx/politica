"""Leitor em streaming dos vínculos da RAIS (microdados públicos, arquivos .7z com um .COMT dentro).

Lê por NOME de coluna (nunca por posição) e devolve só o que a aba de profissões usa:
CBO (6 dígitos), remuneração média nominal, faixa oficial de horas contratadas e se o vínculo estava ativo em 31/12.
Valores ausentes e códigos especiais da RAIS (999997, 999999, vazio) são descartados, nunca viram zero.
Nenhum nome, CPF ou matrícula é lido nem devolvido."""
import csv
import io
import os
import re
import shutil
import tempfile
from typing import Iterable, Iterator, NamedTuple

COL_CBO = "CBO 2002 Ocupação - Código"
COL_REM = "Vl Rem Média Nom"
COL_HORAS = "Qtd Hora Contr"
COL_FAIXA_HORAS = "Faixa Hora Contrat - Código"
COL_ATIVO = "Ind Vínculo Ativo 31/12 - Código"
COLUNAS_OBRIGATORIAS = (COL_CBO, COL_REM, COL_HORAS, COL_FAIXA_HORAS, COL_ATIVO)


class Vinculo(NamedTuple):
    cbo: str
    remuneracao: float
    horas: int
    faixa_horas: int  # código da faixa de horas 1..7 (ver profissoes.FAIXA_HORAS_OFICIAL)


class LayoutInesperado(RuntimeError):
    """O cabeçalho não tem as colunas que o leitor usa: nada é gravado."""


def _numero(texto: str):
    t = (texto or "").strip().strip('"').strip()
    if t == "" or re.fullmatch(r"-?\d+(\.\d+)?", t) is None:
        return None
    return float(t)


def _cbo(texto: str):
    t = (texto or "").strip().strip('"').strip()
    if not re.fullmatch(r"\d{6}", t) or t.startswith("9"):  # 999997/999999 = ausente
        return None
    return t


def ler_linhas(linhas: Iterable[str]) -> Iterator[Vinculo]:
    """linhas: texto já decodificado (cabeçalho na primeira). Gera um Vinculo por linha válida."""
    leitor = csv.reader(linhas)
    cab = next(leitor, None)
    if cab is None:
        raise LayoutInesperado("arquivo vazio")
    cab = [c.strip() for c in cab]
    faltam = [c for c in COLUNAS_OBRIGATORIAS if c not in cab]
    if faltam:
        raise LayoutInesperado("colunas ausentes: " + ", ".join(faltam))
    i = {c: cab.index(c) for c in COLUNAS_OBRIGATORIAS}
    n = len(cab)
    for linha in leitor:
        if len(linha) != n:
            continue  # linha quebrada: descarta, sem adivinhar campos
        if linha[i[COL_ATIVO]].strip() != "1":
            continue
        cbo = _cbo(linha[i[COL_CBO]])
        rem = _numero(linha[i[COL_REM]])
        horas = _numero(linha[i[COL_HORAS]])
        faixa = _numero(linha[i[COL_FAIXA_HORAS]])
        if cbo is None or rem is None or rem <= 0 or horas is None or not (0 < horas <= 80):
            continue
        if faixa is None or int(faixa) not in (1, 2, 3, 4, 5, 6, 7):
            continue
        yield Vinculo(cbo, rem, int(horas), int(faixa))


def ler_comt(caminho: str, encoding: str = "latin-1") -> Iterator[Vinculo]:
    """Lê um arquivo .COMT (texto) em streaming, linha a linha."""
    with open(caminho, "r", encoding=encoding, newline="") as fh:
        yield from ler_linhas(fh)


def ler_7z(caminho_7z: str, encoding: str = "latin-1") -> Iterator[Vinculo]:
    """Extrai cada .COMT do .7z para uma pasta temporária, lê em streaming e apaga a pasta ao final.
    Cada arquivo é extraído sozinho (não o pacote inteiro de uma vez) para caber no disco do robô."""
    import py7zr

    with py7zr.SevenZipFile(caminho_7z) as z:
        nomes = [n for n in z.getnames() if n.upper().endswith(".COMT")]
    for nome in nomes:
        pasta = tempfile.mkdtemp(prefix="rais_")
        try:
            with py7zr.SevenZipFile(caminho_7z) as z:
                z.extract(path=pasta, targets=[nome])
            yield from ler_comt(os.path.join(pasta, nome), encoding=encoding)
        finally:
            shutil.rmtree(pasta, ignore_errors=True)
