"""Segunda rodada do diagnóstico das fontes pendentes: formato dos arquivos que responderam (ANP, Anatel, CNJ, TCU, Câmara, Tesouro)."""
import re

from scripts.diagnostico_ci import cli, ver, zip_remoto

print("##### ANP combustíveis (zip semestral)")
zip_remoto("ANP ca-2026-01", "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/dsas/ca/ca-2026-01.zip", mostrar=("",), linhas=4)
print("##### Anatel banda larga fixa")
zip_remoto("Anatel banda larga fixa", "https://www.anatel.gov.br/dadosabertos/paineis_de_dados/acessos/acessos_banda_larga_fixa.zip", mostrar=("2025", "2026"), linhas=4)
print("##### CNJ Justiça em Números")
zip_remoto("CNJ dea-jn2026", "https://www.cnj.jus.br/wp-content/uploads/2026/06/dea-jn2026.zip", mostrar=("",), linhas=3)
zip_remoto("CNJ 17-set-2026", "https://www.cnj.jus.br/wp-content/uploads/2026/09/17-set-2026.zip", mostrar=("",), linhas=3)
print("##### TCU")
r = ver("TCU inabilitados (fim da página)", "https://contas.tcu.gov.br/ords/condenacao/consulta/inabilitados", n=0)
if r is not None and r.status_code == 200:
    j = r.json()
    print({k: v for k, v in j.items() if k != "items"}, "itens:", len(j.get("items", [])), flush=True)
for u in ("https://sites.tcu.gov.br/dados-abertos/inidoneos-irregulares/",):
    r = cli.get(u)
    print("links da página TCU:", re.findall(r'(?:href|src)="([^"]+)"', r.text)[:40], flush=True)
ver("TCU irregulares (CSV?)", "https://sites.tcu.gov.br/dados-abertos/inidoneos-irregulares/arquivos/condenacao-tcu/irregulares.csv", n=300)
ver("TCU inidôneos (CSV?)", "https://sites.tcu.gov.br/dados-abertos/inidoneos-irregulares/arquivos/licitantes-inidoneos/inidoneos.csv", n=300)
print("##### Câmara: orientação da bancada e CPIs")
r = ver("Câmara votações recentes", "https://dadosabertos.camara.leg.br/api/v2/votacoes", {"itens": 3, "ordem": "DESC", "ordenarPor": "dataHoraRegistro"}, n=0)
try:
    for v in r.json()["dados"][:2]:
        ver(f"orientações {v['id']}", f"https://dadosabertos.camara.leg.br/api/v2/votacoes/{v['id']}/orientacoes", n=700)
except Exception as e:
    print("sem votações:", e, flush=True)
ver("Câmara CPIs (tipo 4)", "https://dadosabertos.camara.leg.br/api/v2/orgaos", {"codTipoOrgao": 4, "itens": 100}, n=300)
print("##### PRF e Tesouro")
r = cli.get("https://www.gov.br/prf/pt-br/acesso-a-informacao/dados-abertos/dados-abertos-da-prf")
print("PRF links:", [x for x in dict.fromkeys(re.findall(r'(https?://[^"\'\s<>]+)', r.text)) if re.search(r"datatran|arquivos|acidente|\.csv|\.zip|drive|dados", x, re.I)][:30], flush=True)
r = ver("Tesouro CKAN orçamento", "https://www.tesourotransparente.gov.br/ckan/api/3/action/package_search", {"q": "orçamento", "rows": 12}, n=0)
try:
    for p in r.json()["result"]["results"]:
        print(" ##", p["name"], "|", p.get("title"), "|", [(x.get("format"), x.get("url")) for x in p.get("resources", [])[:2]], flush=True)
except Exception as e:
    print("ckan:", e, flush=True)
print("fim", flush=True)
