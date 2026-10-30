"""Diagnóstico do CAGED: links da página do PDET e listagem completa do FTP (pastas, meses, arquivos e tamanhos). Saída curta."""
import ftplib
import re

import httpx

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "*/*"}
r = httpx.get("https://acesso.trabalho.gov.br/portal-pdet/o-pdet/portifolio-de-produtos/bases-de-dados.htm", headers=UA, timeout=40, follow_redirects=True)
links = sorted(set(re.findall(r'href="([^"]+)"', r.text)))
print("PDET", r.status_code, len(links), flush=True)
print([l for l in links if re.search(r"caged|ftp|\.xls|\.zip|\.7z|\.csv|tabela|acesso|bi\.|pdet", l, re.I)][:60], flush=True)
txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))
for m in list(re.finditer(r"(?i)caged", txt))[:6]:
    print("  ...", txt[max(0, m.start() - 80):m.start() + 200], flush=True)
try:
    f = ftplib.FTP(timeout=40, encoding="latin-1")
    f.connect("ftp.mtps.gov.br", 21)
    f.login()
    f.cwd("/pdet/microdados/NOVO CAGED")
    itens = f.nlst()
    print("NOVO CAGED:", itens, flush=True)
    anos = sorted(i for i in itens if re.fullmatch(r"\d{4}", i))
    for ano in anos[-2:]:
        f.cwd("/pdet/microdados/NOVO CAGED/" + ano)
        meses = f.nlst()
        print(ano, meses[-4:], flush=True)
        if meses:
            f.cwd("/pdet/microdados/NOVO CAGED/" + ano + "/" + meses[-1])
            for nome in f.nlst()[:8]:
                try:
                    print("   ", nome, f.size(nome), flush=True)
                except Exception:
                    print("   ", nome, flush=True)
    f.quit()
except Exception as e:
    print("FTP ERRO", type(e).__name__, str(e)[:200], flush=True)
print("fim", flush=True)
