"""Dicionário da RAIS (roda no robô; o FTP do Ministério do Trabalho não abre no ambiente do Claude).

1) Lê o leiaute mais novo de vínculos (Layouts/vínculos/*.xls) e tira os pares código CBO (6 dígitos) → nome da ocupação,
   de qualquer aba que os tenha. Grava app/dados/cbo_rais.json (fonte e arquivo de origem junto).
2) Para os anos pedidos (padrão: 2024 e 2023), lista a pasta do ano e mostra o cabeçalho do arquivo regional pequeno (NI),
   para conferir se o leitor (app/rais_leitor.py, colunas por NOME) serve para esses anos antes de uma coleta de horas.

Uso: python -m scripts.rais_dicionario [ano ...]
"""
import io
import json
import os
import re
import sys
import tempfile
from pathlib import Path

from scripts.diag_rais_layout import baixar, conectar

RAIZ = "/pdet/microdados/RAIS"
DESTINO = Path(__file__).resolve().parents[1] / "app" / "dados" / "cbo_rais.json"


def _codigo(v):
    if isinstance(v, float) and v.is_integer():
        v = str(int(v))
    t = re.sub(r"[.\-\s]", "", str(v or ""))
    return t if re.fullmatch(r"\d{6}", t) else None


def pares_cbo(livro) -> tuple[dict, str]:
    """Maior conjunto de (código → nome) achado numa aba: código de 6 dígitos e, na mesma linha, o texto mais longo."""
    melhor, aba = {}, ""
    for planilha in livro.sheets():
        achou = {}
        for r in range(planilha.nrows):
            linha = planilha.row_values(r)
            for i, v in enumerate(linha):
                c = _codigo(v)
                if not c:
                    continue
                textos = [str(x).strip() for x in linha[i + 1:] if isinstance(x, str) and re.search(r"[A-Za-zÀ-ú]{3}", str(x))]
                if textos:
                    achou.setdefault(c, max(textos, key=len))
                break
        if len(achou) > len(melhor):
            melhor, aba = achou, planilha.name
    return melhor, aba


def dicionario(ftp) -> dict:
    import xlrd
    ftp.cwd(f"{RAIZ}/Layouts")
    pasta = next((p for p in ftp.nlst() if p.lower().startswith("v") and "nculo" in p.lower()), None)
    ftp.cwd(f"{RAIZ}/Layouts/{pasta}")
    xls = sorted((n for n in ftp.nlst() if n.lower().endswith((".xls", ".xlsx"))),
                 key=lambda n: int((re.findall(r"(\d{4})", n) or ["0"])[-1]))
    print("leiautes:", xls)
    arq = xls[-1]
    bruto = baixar(ftp, arq)
    nomes, aba = pares_cbo(xlrd.open_workbook(file_contents=bruto))
    print(f"{arq}: aba '{aba}' com {len(nomes)} ocupações")
    return {"fonte": f"RAIS — dicionário oficial ({RAIZ}/Layouts/{pasta}/{arq}, aba {aba})", "arquivo": arq, "nomes": dict(sorted(nomes.items()))}


def cabecalho(ftp, ano: int):
    import py7zr
    try:
        ftp.cwd(f"{RAIZ}/{ano}")
    except Exception as e:
        print(f"\n{ano}: pasta não abriu ({e})")
        return
    nomes = sorted(ftp.nlst())
    print(f"\n{ano}:", nomes)
    ni = next((n for n in nomes if "VINC" in n.upper() and "NI" in n.upper()), None)
    if not ni:
        print(f"{ano}: sem arquivo NI de vínculos")
        return
    dados = baixar(ftp, ni)
    pasta = tempfile.mkdtemp()
    with py7zr.SevenZipFile(io.BytesIO(dados)) as z:
        z.extractall(path=pasta)
    for raiz, _, arqs in os.walk(pasta):
        for a in arqs:
            with open(os.path.join(raiz, a), "rb") as fh:
                linhas = fh.read(200_000).decode("latin-1", errors="replace").splitlines()
            print(f"{ano}/{ni} -> {a}: CABECALHO = {linhas[0][:1500]}")
            for amostra in linhas[1:3]:
                print("AMOSTRA:", amostra[:400])


def main(argv):
    anos = [int(a) for a in argv] or [2024, 2023]
    ftp = conectar()
    try:
        doc = dicionario(ftp)
        DESTINO.write_text(json.dumps(doc, ensure_ascii=False, indent=0), encoding="utf-8")
        prof = Path(__file__).resolve().parents[1] / "app" / "dados" / "profissoes_rais.json"
        if prof.exists():
            cods = json.loads(prof.read_text(encoding="utf-8"))["profissoes"]
            falt = [c for c in cods if c not in doc["nomes"]]
            print(f"profissões da RAIS sem nome no dicionário: {len(falt)} {falt[:30]}")
        for ano in anos:
            cabecalho(ftp, ano)
    finally:
        try:
            ftp.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main(sys.argv[1:])
