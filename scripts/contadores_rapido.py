"""Lê os contadores do Impostômetro e do Gasto Brasil e grava site/dados/contadores_externos.json.

  python -m scripts.contadores_rapido [site/dados]

Roda junto com as notícias (.github/workflows/noticias.yml), a cada 15 minutos. O arquivo já vem no formato de
GET /contadores; o site e a API usam por cima da conta própria enquanto a leitura for recente (app/contadores_externos.py).
Se uma das fontes falhar, mantém a última leitura dela; se as duas falharem ou a conferência reprovar, não grava nada.
"""
import json
import sys
from pathlib import Path

from app.collectors import contadores_externos as ce


def _tentar(f):
    try:
        return f(), None
    except Exception as e:  # noqa: BLE001 - uma fonte fora do ar não derruba a outra
        return None, f"{f.__name__}: {type(e).__name__}: {str(e)[:200]}"


def main(argv):
    pasta = Path(argv[0] if argv else "site/dados")
    arq = pasta / "contadores_externos.json"
    imp, e1 = _tentar(ce.ler_impostometro)
    gas, e2 = _tentar(ce.ler_gastometro)
    if not imp and not gas:
        sys.exit("Nenhum contador respondeu: " + "; ".join(x for x in (e1, e2) if x))
    problemas = ce.conferir(imp, gas)
    if problemas:
        sys.exit("Leitura reprovada na conferência, nada foi gravado: " + "; ".join(problemas))
    novo = ce.montar(imp, gas)
    try:  # a fonte que falhou agora continua com a última leitura boa
        antigo = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        antigo = {}
    for chave, lido in (("impostometro", imp), ("gastometro", gas)):
        if not lido and antigo.get(chave):
            novo[chave] = antigo[chave]
    novo["avisos"] = [x for x in (e1, e2) if x]
    pasta.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(novo, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("contadores gravados:", ", ".join(k for k in ("impostometro", "gastometro") if k in novo), "| avisos:", novo["avisos"] or "nenhum")


if __name__ == "__main__":
    main(sys.argv[1:])
