"""Diagnóstico do INEP (IDEB/IGC): acha os links dos arquivos de dados. Roda no GitHub Actions (diag-inep.yml).

O servidor download.inep.gov.br não envia o certificado intermediário; a cadeia é completada com o certificado do endereço AIA do próprio certificado (verificação mantida)."""
import re
import ssl
import subprocess
import tempfile

import certifi
import httpx

AIA_CONHECIDO = "http://secure.globalsign.com/cacert/rnpicpedugr46ovtlsca2025.crt"  # visto no certificado em 30/10/2026
aia = AIA_CONHECIDO
try:
    pem_srv = subprocess.run("echo | timeout 40 openssl s_client -connect download.inep.gov.br:443 -servername download.inep.gov.br 2>/dev/null | openssl x509 -noout -text",
                             shell=True, capture_output=True, text=True, timeout=60).stdout
    m = re.search(r"CA Issuers - URI:(\S+)", pem_srv)
    aia = m.group(1) if m else AIA_CONHECIDO
except subprocess.TimeoutExpired:
    pass
print("AIA:", aia, flush=True)
der = httpx.get(aia, timeout=30).content
pem = der.decode() if der.startswith(b"-----") else ssl.DER_cert_to_PEM_cert(der)
with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
    f.write(open(certifi.where()).read() + "\n" + pem)
cli = httpx.Client(verify=f.name, timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"})
paginas = ["https://www.gov.br/inep/pt-br/areas-de-atuacao/pesquisas-estatisticas-e-indicadores/ideb/resultados",
           "https://www.gov.br/inep/pt-br/areas-de-atuacao/pesquisas-estatisticas-e-indicadores/ideb",
           "https://www.gov.br/inep/pt-br/areas-de-atuacao/pesquisas-estatisticas-e-indicadores/indicadores-educacionais/indice-geral-de-cursos-igc",
           "https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/indicadores-educacionais/indice-de-desenvolvimento-da-educacao-basica-ideb"]
for u in paginas:
    for cl in (cli, httpx.Client(timeout=30, follow_redirects=True)):
        try:
            r = cl.get(u)
            links = sorted(set(re.findall(r'href="([^"]*(?:download\.inep|\.zip|\.xlsx?|\.ods)[^"]*)"', r.text)))
            print(f"\n=== {u}\n  HTTP {r.status_code} {len(r.text)} bytes; links de arquivo: {len(links)}")
            for l in links[:60]:
                print("   ", l)
            if not links:
                print(re.sub(r"\s+", " ", r.text)[:600])
            break
        except Exception as e:
            print(f"\n=== {u}: ERRO {type(e).__name__} {e}", flush=True)
