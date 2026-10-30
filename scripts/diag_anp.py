"""ANP: colunas e uma amostra do zip semestral de preços de combustíveis (saída curta; GET com User-Agent de navegador, o HEAD dá 403)."""
import io
import zipfile

import httpx

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "*/*"}
cli = httpx.Client(timeout=180, follow_redirects=True, headers=UA)
for nome in ("ca-2026-01.zip", "ca-2025-02.zip"):
    r = cli.get("https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/dsas/ca/" + nome)
    print(nome, r.status_code, len(r.content), flush=True)
    if r.status_code == 200:
        z = zipfile.ZipFile(io.BytesIO(r.content))
        for n in z.namelist():
            txt = z.read(n)
            print("  arquivo:", n, len(txt), flush=True)
            print(txt[:700].decode("latin-1"), flush=True)
        break
print("fim", flush=True)
