"""Confere se saiu uma RAIS mais nova e COMPLETA (os 7 arquivos regionais) do que a gravada em app/dados/profissoes_rais.json.

Imprime e, no GitHub Actions, grava em $GITHUB_OUTPUT: novo=<ano> (ou novo= vazio) e atual=<ano>. Só lê o FTP; não baixa nada.
Uso: python -m scripts.rais_monitor
"""
import json
import os
import sys

from app.collectors import rais_profissoes as C


def main() -> int:
    atual = 0
    if C.DESTINO.exists():
        atual = int(json.loads(C.DESTINO.read_text(encoding="utf-8")).get("ano_referencia") or 0)
    ftp = C.conectar()
    try:
        ftp.cwd(C.RAIZ)
        try:
            mais_novo = C.escolher_ano(ftp.nlst(), C._listar_ano(ftp))
        except C.ColetaIncompleta as e:
            print("nenhum ano completo:", e)
            mais_novo = 0
    finally:
        C._fechar(ftp)
    novo = mais_novo if mais_novo > atual else ""
    print(f"gravado: {atual or 'nenhum'}; mais novo completo no FTP: {mais_novo or 'nenhum'}; novo: {novo or 'não'}")
    saida = os.environ.get("GITHUB_OUTPUT")
    if saida:
        with open(saida, "a", encoding="utf-8") as f:
            f.write(f"novo={novo}\natual={atual}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
