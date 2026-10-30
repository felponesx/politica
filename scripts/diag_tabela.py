"""Diagnóstico em lote (parte 2): Social, Servidores, SIDRA, ANP, ANEEL, TSE FEFC. Roda no GitHub Actions (diag-tabela.yml)."""
from scripts.diagnostico_ci import inicio_csv, ver, zip_remoto

P = "https://portaldatransparencia.gov.br/download-de-dados"
print("##### SOCIAL")
for base in ("novo-bolsa-familia", "bpc"):
    zip_remoto(f"{base} 202609", f"{P}/{base}/202609", mostrar=("",), linhas=3)
print("##### SERVIDORES")
zip_remoto("servidores 202609", f"{P}/servidores/202609", mostrar=("Cadastro", "Remuneracao"), linhas=3)
zip_remoto("viagens 2025", f"{P}/viagens/2025", mostrar=("Viagem",), linhas=3)
print("##### SIDRA")
for t in ("/t/4099/n3/all/v/4099/p/last", "/t/5434/n3/all/v/4090/p/last", "/t/7060/n7/all/v/63/p/last%201"):
    ver(f"sidra {t}", "https://apisidra.ibge.gov.br/values" + t, n=500)
print("##### ANP / ANEEL / TSE")
inicio_csv("ANP ca-2025-02", "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/arquivos/shpc/dsas/ca/ca-2025-02.csv", kb=120)
inicio_csv("ANEEL tarifas", "https://dadosabertos.aneel.gov.br/dataset/5a583f3e-1646-4f67-bf0f-69db4203e89e/resource/fcf2906c-7c32-4b9b-a637-054e7a5234f4/download/tarifas-homologadas-distribuidoras-energia-eletrica.csv", kb=120)
zip_remoto("TSE FEFC FP 2024", "https://cdn.tse.jus.br/estatistica/sead/odsele/fefc_fp/fefc_fp_2024.zip", mostrar=("",), linhas=3)
print("fim", flush=True)
