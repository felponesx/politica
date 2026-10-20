"""Busca na internet pela Perplexity Search API, no terminal (precisa de PERPLEXITY_API_KEY no ambiente ou no .env).

    python -m scripts.busca_web "votação reforma tributária Senado" [mais consultas…] [--max 5] [--dominio gov.br]
        [--recencia week] [--idioma pt] [--pais BR] [--json]
"""
import argparse
import json
import sys

from app import busca_web


def main(argv=None):
    ap = argparse.ArgumentParser(description="Busca na internet (Perplexity Search API).")
    ap.add_argument("consultas", nargs="+", help="até 5 consultas (cobradas como uma busca)")
    ap.add_argument("--max", type=int, default=10, help="resultados por consulta (1 a 20)")
    ap.add_argument("--pais", default="BR")
    ap.add_argument("--idioma", action="append", help="código ISO 639-1, ex.: pt (pode repetir)")
    ap.add_argument("--dominio", action="append", help='só este site ("gov.br") ou, com "-", menos este (pode repetir)')
    ap.add_argument("--recencia", choices=busca_web.RECENCIAS)
    ap.add_argument("--json", action="store_true", help="imprime a resposta inteira em JSON")
    a = ap.parse_args(argv)
    try:
        r = busca_web.buscar(a.consultas, a.max, a.pais, a.idioma, a.dominio, a.recencia)
    except (busca_web.SemChave, busca_web.LimiteDiario, ValueError) as e:
        print(e, file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    for i, x in enumerate(r["resultados"], 1):
        print(f"{i}. {x['titulo']}\n   {x['url']}" + (f"  ({x['data']})" if x.get("data") else ""))
        if x["trecho"]:
            print("   " + x["trecho"][:240].replace("\n", " "))
    print(f"\n{len(r['resultados'])} resultados. {r['aviso']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
