"""Diagnóstico em lote das fontes da tabela de lacunas (Social, Servidores, Dinheiro, Trabalho, Infra, Trânsito...). Roda no GitHub Actions (diag-tabela.yml)."""
from scripts.diagnostico_ci import ckan, inicio_csv, links, planilha, ver, zip_remoto

P = "https://portaldatransparencia.gov.br/download-de-dados"
print("##### SOCIAL")
for base in ("novo-bolsa-familia", "bolsa-familia-pagamentos", "bpc", "auxilio-brasil"):
    zip_remoto(f"{base} 202609", f"{P}/{base}/202609", mostrar=("",), linhas=3)
print("##### SERVIDORES")
for base in ("servidores", "viagens", "pensionistas"):
    zip_remoto(f"{base}", f"{P}/{base}/{'2025' if base == 'viagens' else '202609'}", mostrar=("",), linhas=3)
print("##### SIDRA (trabalho e renda)")
for t in ("/t/4099/n3/all/v/4099/p/last", "/t/5434/n3/all/v/4090/p/last", "/t/7060/n7/all/v/63/p/last%201", "/t/6381/n1/all/v/4099/p/last%203"):
    ver(f"sidra {t}", "https://apisidra.ibge.gov.br/values" + t, n=700)
print("##### ANP / ANEEL / ANATEL / PRF")
links("ANP preços", "https://www.gov.br/anp/pt-br/centrais-de-conteudo/dados-abertos/serie-historica-de-precos-de-combustiveis")
ckan("ANEEL tarifas", "https://dadosabertos.aneel.gov.br", "tarifas distribuidoras")
links("PRF acidentes", "https://www.gov.br/prf/pt-br/acesso-a-informacao/dados-abertos/dados-abertos-acidentes")
ckan("dados.gov.br anatel", "https://dados.gov.br", "anatel acessos banda larga")
print("##### DINHEIRO")
links("Receita gastos tributários", "https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/relatorios/renuncia-fiscal")
ckan("TSE fundo partidário", "https://dadosabertos.tse.jus.br", "fundo partidario")
ckan("TSE doadores", "https://dadosabertos.tse.jus.br", "prestacao de contas receitas")
print("##### CAGED / CNJ")
links("CAGED ftp", "https://ftp.mtps.gov.br/pdet/microdados/NOVO%20CAGED/", padrao=r'href="([^"]+)"')
ver("CNJ painel", "https://justica-em-numeros.cnj.jus.br/", n=300)
print("fim", flush=True)
