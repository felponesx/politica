"""Verificador com Gemini: lê a cópia dos dados (site/dados), manda em pedaços ao Gemini e grava SUGESTÕES de correção.

Não altera nenhum dado. Cada suspeita vira uma linha de CSV para revisão humana, com a fonte citada pelo modelo.
Modelos de linguagem erram números: uma sugestão só vale depois de conferida na fonte oficial.

Uso:
  python -m scripts.verificar_gemini site/dados saida.csv --dry-run          # só conta os pedaços
  GEMINI_API_KEY=... python -m scripts.verificar_gemini site/dados saida.csv --limite 50
Variáveis: GEMINI_API_KEY (obrigatória sem --dry-run), GEMINI_MODEL (padrão gemini-2.5-flash).
"""
import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import httpx

MODELO_PADRAO = "gemini-2.5-flash"
URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
TAMANHO_PEDACO = 40_000  # caracteres por pedido
COLUNAS = ["arquivo", "caminho", "problema", "valor_atual", "sugestao", "fonte", "confianca"]

INSTRUCAO = """Você é um verificador de dados públicos brasileiros (BRASIL+). Analise o trecho JSON abaixo.
Procure apenas problemas concretos: valores impossíveis ou fora de escala, somas que não batem com o total dado,
datas vencidas ou erradas, nomes ou siglas trocados, CNPJ/CPF mal formados, textos com acento quebrado,
campos vazios onde deveria haver dado, e mensagens de erro guardadas como se fossem dados.
Não invente valores. Se não souber a resposta correta, deixe "sugestao" vazia.
Responda SOMENTE um JSON: uma lista de objetos com as chaves
"caminho" (chave ou índice até o valor), "problema", "valor_atual", "sugestao", "fonte" (de onde viria a correção; vazio se não souber), "confianca" (alta, media ou baixa).
Se não houver problema, responda []."""


def pedacos(pasta: Path):
    """Arquivos JSON da cópia em pedaços de até TAMANHO_PEDACO caracteres, sem cortar um JSON no meio."""
    for arq in sorted(pasta.rglob("*.json")):
        if arq.name == "revisao.json":
            continue
        try:
            dados = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            yield arq.relative_to(pasta).as_posix(), "(arquivo ilegível)"
            continue
        if isinstance(dados, list) and len(json.dumps(dados, ensure_ascii=False)) > TAMANHO_PEDACO:
            atual: list = []
            for item in dados:
                atual.append(item)
                if len(json.dumps(atual, ensure_ascii=False)) > TAMANHO_PEDACO:
                    yield arq.relative_to(pasta).as_posix(), json.dumps(atual[:-1], ensure_ascii=False)
                    atual = [item]
            if atual:
                yield arq.relative_to(pasta).as_posix(), json.dumps(atual, ensure_ascii=False)
        else:
            yield arq.relative_to(pasta).as_posix(), json.dumps(dados, ensure_ascii=False)


def perguntar(cliente, chave: str, modelo: str, arquivo: str, texto: str) -> list[dict]:
    corpo = {"contents": [{"parts": [{"text": f"{INSTRUCAO}\n\nArquivo: {arquivo}\n\n{texto}"}]}],
             "generationConfig": {"responseMimeType": "application/json", "temperature": 0}}
    for tentativa in range(4):
        r = cliente.post(URL.format(modelo=modelo), json=corpo, headers={"x-goog-api-key": chave}, timeout=120)
        if r.status_code in (429, 500, 503):
            time.sleep(min(10 * (tentativa + 1), 60))
            continue
        r.raise_for_status()
        texto_resp = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        achados = json.loads(texto_resp)
        return achados if isinstance(achados, list) else []
    raise RuntimeError(f"Gemini indisponível para {arquivo}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pasta")
    ap.add_argument("saida")
    ap.add_argument("--dry-run", action="store_true", help="só conta os pedaços, sem chamar o Gemini")
    ap.add_argument("--limite", type=int, default=0, help="máximo de pedaços a enviar (0 = todos)")
    a = ap.parse_args(argv)

    lista = list(pedacos(Path(a.pasta)))
    if a.limite:
        lista = lista[: a.limite]
    tam = sum(len(t) for _, t in lista)
    print(f"{len(lista)} pedaços, {tam/1e6:.1f} milhões de caracteres")
    if a.dry_run:
        return 0

    chave = os.environ.get("GEMINI_API_KEY")
    if not chave:
        print("Defina GEMINI_API_KEY no ambiente (não grave a chave em arquivo).", file=sys.stderr)
        return 2
    modelo = os.environ.get("GEMINI_MODEL", MODELO_PADRAO)
    linhas = []
    with httpx.Client() as cli, open(a.saida, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=COLUNAS, delimiter=";")
        w.writeheader()
        for i, (arq, texto) in enumerate(lista, 1):
            for achado in perguntar(cli, chave, modelo, arq, texto):
                linha = {c: str(achado.get(c, "") or "") for c in COLUNAS}
                linha["arquivo"] = arq
                w.writerow(linha)
                linhas.append(linha)
            print(f"[{i}/{len(lista)}] {arq}", flush=True)
    print(f"{len(linhas)} sugestões gravadas em {a.saida}. Nenhum dado foi alterado.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
