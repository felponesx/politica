"""Diagnóstico do INEP (IDEB/IGC): cadeia de certificados, certificado intermediário (AIA) e fontes alternativas. Roda no GitHub Actions (diag-inep.yml)."""
import re
import ssl
import subprocess
import tempfile

import certifi
import httpx


def sh(cmd, n=3000):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    print(f"$ {cmd}\n{(r.stdout + r.stderr)[:n]}", flush=True)
    return r.stdout


saida = sh("echo | openssl s_client -connect download.inep.gov.br:443 -servername download.inep.gov.br -showcerts 2>/dev/null", 12000)
sh("echo | openssl s_client -connect download.inep.gov.br:443 -servername download.inep.gov.br 2>/dev/null | openssl x509 -noout -subject -issuer -text | grep -iE 'subject:|issuer:|CA Issuers'")
m = re.search(r"CA Issuers - URI:(\S+)", sh("echo | openssl s_client -connect download.inep.gov.br:443 -servername download.inep.gov.br 2>/dev/null | openssl x509 -noout -text", 20000))
if m:
    url = m.group(1)
    print("AIA:", url)
    r = httpx.get(url, timeout=60)
    cert = r.content
    pem = cert.decode() if cert.startswith(b"-----") else ssl.DER_cert_to_PEM_cert(cert)
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
        f.write(open(certifi.where()).read() + "\n" + pem)
    print("bundle:", f.name)
    for u in ("https://download.inep.gov.br/", "https://download.inep.gov.br/educacao_basica/portal_ideb/planilhas_para_download/"):
        try:
            rr = httpx.get(u, verify=f.name, timeout=60, follow_redirects=True)
            print(u, rr.status_code, rr.headers.get("content-type"), len(rr.content))
            print(rr.text[:1500])
            print(re.findall(r'href="([^"]+\.(?:zip|xlsx?|ods))"', rr.text)[:40])
        except Exception as e:
            print(u, "ERRO", type(e).__name__, e)
for u in ("https://www.ipeadata.gov.br/api/odata4/Metadados?$filter=contains(SERNOME,'IDEB')&$select=SERCODIGO,SERNOME,UNINOME",
          "https://www.ipeadata.gov.br/api/odata4/Metadados?$filter=contains(SERNOME,'Ideb')&$select=SERCODIGO,SERNOME"):
    try:
        rr = httpx.get(u, timeout=60)
        print(u, rr.status_code, rr.text[:1500])
    except Exception as e:
        print(u, "ERRO", e)
