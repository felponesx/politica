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
import io
import zipfile

import openpyxl

B = "https://download.inep.gov.br/"
NOMES = ["divulgacao_regioes_ufs_ideb_{a}.xlsx", "divulgacao_regioes_ufs_ideb_{a}.zip", "divulgacao_anos_iniciais_municipios_{a}.zip", "divulgacao_anos_iniciais_escolas_{a}.zip",
         "divulgacao_anos_finais_escolas_{a}.zip", "divulgacao_ensino_medio_escolas_{a}.zip", "divulgacao_brasil_ideb_{a}.xlsx", "ideb_{a}.zip", "Ideb_{a}.zip",
         "divulgacao_regioes_ufs_{a}.xlsx", "divulgacao_ufs_ideb_{a}.xlsx", "resultados_ideb_{a}.zip", "divulgacao_ideb_{a}.zip"]
achados = {}
print("--- onde estão os arquivos de 2023 (e 2025, se houver)", flush=True)
for ano in ():
    for pasta in ("ideb/", f"educacao_basica/portal_ideb/planilhas_para_download/{ano}/", f"ideb/{ano}/", f"ideb/resultados/{ano}/", f"educacao_basica/ideb/{ano}/",
                  "ideb/resultados/", f"ideb/planilhas_para_download/{ano}/", f"ideb/divulgacao/{ano}/", f"educacao_basica/portal_ideb/planilhas_para_download/", f"ideb/{ano}/planilhas/",
                  f"educacao_basica/portal_ideb/{ano}/", f"ideb/divulgacao_{ano}/"):
        for n in NOMES:
            u = B + pasta + n.format(a=ano)
            try:
                h = cli.head(u)
                if h.status_code == 200:
                    print(200, h.headers.get("content-length"), u, flush=True)
                    achados[(ano, n)] = u
            except Exception as e:
                print("ERRO", type(e).__name__, u, flush=True)


def olhar(nome, conteudo, linhas=8):
    wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    print(f"\n##### {nome}: abas {wb.sheetnames}", flush=True)
    for ws in wb.worksheets[:6]:
        print(f"  -- aba {ws.title!r}", flush=True)
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            if i >= linhas:
                break
            print("    ", [c for c in row][:22], flush=True)


def abrir_zip(u, linhas):
    z = zipfile.ZipFile(io.BytesIO(cli.get(u, timeout=300).content))
    print("\nZIP", u, [(i.filename, i.file_size) for i in z.infolist()], flush=True)
    for nome in z.namelist()[:3]:
        if nome.lower().endswith(".xlsx"):
            olhar(nome, z.read(nome), linhas)
        elif nome.lower().endswith((".csv", ".txt")):
            print("##### csv", nome, flush=True)
            for l in z.read(nome)[:3000].decode("latin-1").splitlines()[:6]:
                print("    ", l[:400], flush=True)


import hashlib
import re as _re

print("AIA SHA256:", hashlib.sha256(der).hexdigest(), "bytes", len(der), flush=True)
R = B + "ideb/resultados/"


def codigos(nome, conteudo):
    wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    for ws in wb.worksheets[:3]:
        linhas = []
        for i, row in enumerate(ws.iter_rows(values_only=True)):
            linhas.append(row)
            if i >= 14:
                break
        grupo = next((r for r in linhas if any(isinstance(c, str) and "Taxa de Aprova" in c for c in r)), None)
        cod = next((r for r in linhas if any(isinstance(c, str) and c.startswith("VL_") for c in r)), None)
        print(f"\n## {nome} / {ws.title}: linha de grupos={linhas.index(grupo) if grupo else None}, de códigos={linhas.index(cod) if cod else None}", flush=True)
        if cod:
            pref = {}
            for c in cod:
                if isinstance(c, str) and c.startswith("VL_"):
                    pref.setdefault(_re.sub(r"\d{4}", "AAAA", c), []).append(c)
            for k, v in pref.items():
                print("   cod", k, len(v), v[:2], v[-1], flush=True)
        if grupo:
            print("   grupos:", [g for g in grupo if g], flush=True)
        j = linhas.index(cod) + 1 if cod else 9
        for r in linhas[j:j + 3]:
            print("   dado:", [c for c in r][:6], "...", [c for c in r][-8:], flush=True)


z = zipfile.ZipFile(io.BytesIO(cli.get(R + "divulgacao_regioes_ufs_ideb_2025.zip", timeout=300).content))
for nome in z.namelist():
    if nome.lower().endswith(".xlsx"):
        codigos("UF 2025", z.read(nome))
z = zipfile.ZipFile(io.BytesIO(cli.get(R + "divulgacao_ensino_medio_escolas_2025.zip", timeout=300).content))
for nome in z.namelist():
    if nome.lower().endswith(".xlsx"):
        codigos("escolas EM 2025", z.read(nome))
print("fim", flush=True)
