"""Terceira rodada: colunas do arquivo da ANP e dicionário de variáveis do Justiça em Números (CNJ)."""
import io
import re
import zipfile

from scripts.diagnostico_ci import cli, zip_remoto

zip_remoto("ANP ca-2026-01", "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/dsas/ca/ca-2026-01.zip", mostrar=("",), linhas=4)
with cli.stream("GET", "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/dsas/ca/ca-2021-02.csv") as r:
    print("ANP csv 2021-02:", r.status_code, r.headers.get("content-length"), flush=True)
    for bloco in r.iter_bytes(2048):
        print(bloco.decode("latin-1"), flush=True)
        break
r = cli.get("https://www.cnj.jus.br/wp-content/uploads/2026/09/17-set-2026.zip")
z = zipfile.ZipFile(io.BytesIO(r.content))
nome = [n for n in z.namelist() if n.startswith("Vari")][0]
txt = z.read(nome).decode("utf-8-sig", "replace")
print("CNJ dicionário:", len(txt.splitlines()), "linhas", flush=True)
for linha in txt.splitlines():
    if re.search(r"tempo|congestion|casos novos|pendentes|baixados|sentenç|magistrados|produtividade", linha, re.I):
        print("  ", linha[:170], flush=True)
print("fim", flush=True)
