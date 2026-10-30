"""Testa as fontes novas sugeridas (TCU API, Querido Diário, ANAC, PRF, IGC, IBAMA, INPE queimadas, servidores, Receita, lista suja, CAGED FTP, TerraBrasilis).
Saída curta: status, tipo, tamanho e os links de arquivos de dados. Roda no GitHub Actions (diag-novas.yml)."""
import ftplib
import re

import httpx

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36", "Accept": "*/*"}
cli = httpx.Client(timeout=60, follow_redirects=True, headers=UA)
DADOS = r'href="([^"]+\.(?:csv|xlsx?|zip|json|ods|txt|gz|7z)[^"]*)"'


def ver(nome, url, links=False, n=400, padrao=DADOS, nlinks=14):
    try:
        r = cli.get(url)
        print(f"\n== {nome}: {r.status_code} {r.headers.get('content-type','')[:40]} {len(r.content)}B {str(r.url)[:110]}", flush=True)
        if links and r.status_code == 200:
            achados = list(dict.fromkeys(re.findall(padrao, r.text, re.I)))
            print(f"   {len(achados)} links:", achados[:nlinks], flush=True)
        elif r.status_code == 200:
            print("  ", re.sub(r"\s+", " ", r.text[:n]), flush=True)
    except Exception as e:
        print(f"\n== {nome}: ERRO {type(e).__name__} {str(e)[:100]}", flush=True)


ver("TCU API contas irregulares", "https://certidoes.apps.tcu.gov.br/api/publico/responsaveis-contas-irregulares", n=500)
ver("TCU página", "https://sites.tcu.gov.br/dados-abertos/inidoneos-irregulares/", links=True, padrao=r'(?:href|src)="([^"]*(?:irregular|csv|json|api)[^"]*)"')
ver("Querido Diário API", "https://api.queridodiario.ok.org.br/gazettes?size=1", n=400)
ver("ANAC aeródromos CSV", "https://sistemas.anac.gov.br/dadosabertos/Aerodromos/Aer%C3%B3dromos%20P%C3%BAblicos/Lista%20de%20aer%C3%B3dromos%20p%C3%BAblicos/AerodromosPublicos.csv", n=400)
ver("ANAC página", "https://www.anac.gov.br/acesso-a-informacao/dados-abertos/areas-de-atuacao/aerodromos/lista-de-aerodromos-publicos-v2", links=True)
ver("PRF página", "https://www.gov.br/prf/pt-br/acesso-a-informacao/dados-abertos/dados-abertos-da-prf", links=True, padrao=r'(https?://[^"\s<>]*(?:datatran|acidentes|\.zip|\.csv)[^"\s<>]*)')
ver("IGC INEP página", "https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/indicadores-educacionais/indicadores-de-qualidade-da-educacao-superior", links=True)
ver("IBAMA dataset", "https://dadosabertos.ibama.gov.br/pt_BR/dataset/fiscalizacao-auto-de-infracao", links=True)
ver("IBAMA CKAN API", "https://dadosabertos.ibama.gov.br/api/3/action/package_show?id=fiscalizacao-auto-de-infracao", n=600)
ver("INPE queimadas dados abertos", "https://data.inpe.br/queimadas/dados-abertos/", links=True, padrao=r'href="([^"]+)"', nlinks=20)
ver("Servidores observatório", "https://www.gov.br/servidor/pt-br/observatorio-de-pessoal-govbr/portal-da-transparencia", links=True)
ver("Receita gastos tributários", "https://www.gov.br/receitafederal/pt-br/centrais-de-conteudo/publicacoes/relatorios/renuncia/gastos-tributarios-bases-efetivas/", links=True)
ver("MTE trabalho escravo", "https://www.gov.br/trabalho-e-emprego/pt-br/assuntos/inspecao-do-trabalho/areas-de-atuacao/combate-ao-trabalho-escravo-e-analogo-ao-de-escravo", links=True)
ver("TerraBrasilis downloads", "https://terrabrasilis.dpi.inpe.br/downloads/", links=True, padrao=r'href="([^"]+)"', nlinks=20)
ver("Câmara orientações (votação com CSV)", "https://dadosabertos.camara.leg.br/api/v2/votacoes/2367548-196", n=300)
try:
    f = ftplib.FTP(timeout=25)
    f.connect("ftp.mtps.gov.br", 21)
    f.login()
    f.cwd("/pdet/microdados")
    print("\n== CAGED FTP: ok", f.nlst()[:12], flush=True)
    f.quit()
except Exception as e:
    print(f"\n== CAGED FTP: ERRO {type(e).__name__} {str(e)[:120]}", flush=True)
print("fim", flush=True)
