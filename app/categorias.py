"""Categorias das fontes para o painel. São as MESMAS seções do menu do site (`NAV` em site/index.html): cada seção do site tem uma
categoria, e cada coleta do BRASIL+ cai em uma delas. O teste `tests/test_categorias.py` confere que a lista bate com o menu do site.

Seções sem coleta própria (dados derivados de outras seções ou do próprio site) aparecem no painel com a nota "sem coleta própria".
"""

CATEGORIAS = [
    {"id": "gastos", "nome": "Gastos Públicos"},
    {"id": "arrecadacao", "nome": "Arrecadação"},
    {"id": "dividas", "nome": "Dívidas"},
    {"id": "orgaos", "nome": "Órgãos"},
    {"id": "pessoas", "nome": "Candidatos e Indicações"},
    {"id": "eleicoes", "nome": "Eleições"},
    {"id": "seguranca", "nome": "Segurança Pública"},
    {"id": "saude", "nome": "Saúde"},
    {"id": "social", "nome": "Social e Trabalho"},
    {"id": "ambiente", "nome": "Meio ambiente"},
    {"id": "empresas", "nome": "Empresas e Contratos"},
    {"id": "obras", "nome": "Obras"},
    {"id": "leis", "nome": "Leis e Projetos"},
    {"id": "escandalos", "nome": "Escândalos e crimes"},
    {"id": "noticias", "nome": "Notícias"},
    {"id": "ensino", "nome": "Ensino"},
    {"id": "premios", "nome": "Prêmios"},
    {"id": "indicadores", "nome": "Indicadores"},
    {"id": "comparar", "nome": "Comparar"},
    {"id": "relatorios", "nome": "Relatórios e Dados"},
]

# seções que o site mostra mas que não têm coleta própria no painel:
#   comparar: monta a comparação com dados de outras seções
#   premios: história e imagens vêm da Wikipédia pelo script scripts/premios_wiki.py (ainda não é uma tarefa do programa)
SEM_COLETA_PROPRIA = {"comparar", "premios"}

MAPA = {
    "gastos": """camara-despesas senado-ceaps transparencia-cartao transparencia-emendas transparencia-gastos
        transparencia-gastos-todos siconfi-despesas-funcao""",
    "arrecadacao": """receita-arrecadacao receita-renuncia-fiscal siconfi-receitas siconfi-tributos tesouro-transferencias
        reforma-tributaria receita-cbs cgibs-ibs""",
    "dividas": """siconfi-divida pgfn-divida-ativa tesouro-capag bcb-scr-estados receita-empresas-porte
        receita-recuperacao-judicial""",
    "orgaos": "transparencia-orgaos transparencia-orcamento transparencia-servidores transparencia-viagens",
    "pessoas": "tse-candidatos tse-bens camara-deputados senado-senadores camara-orgaos congresso-atuacao",
    "eleicoes": "tse-resultados tse-doadores tse-fundos tse-contas",
    "seguranca": "seguranca-anuario seguranca-efetivo seguranca-prisional seguranca-sinesp isp-rj-batalhoes prf-acidentes",
    "saude": "saude-ubs saude-mais-medicos saude-datasus",
    "social": """transparencia-social ibge-trabalho ibge-indicadores-sociais ibge-saneamento caged-saldos
        caged-estoque-referencia""",
    "ambiente": """inpe-desmatamento inpe-prodes-mata-atlantica inpe-queimadas mapbiomas-alertas mapbiomas-alertas-territorio
        desastres""",
    "empresas": "pncp-contratos transparencia-contratos cnpj-fornecedores ibge-empresas-economia",
    "obras": "obrasgov-obras",
    "leis": """camara-proposicoes camara-proposicoes-detalhe camara-proposicoes-situacao camara-tramitacoes camara-votacoes
        camara-orientacoes senado-votacoes senado-situacao senado-materias congresso-agenda congresso-cpis assembleias
        assembleia-arquivo legislacao-normas lexml-estaduais cnj-justica""",
    "escandalos": """escandalos-fila cgu-sancoes ibama-multas mte-lista-suja tcu-inabilitados tcu-contas-irregulares""",
    "noticias": "noticias-politica querido-diario",
    "ensino": "ensino-ideb inep-igc inep-censo-ies",
    "indicadores": """ibge-indicadores bcb-series bcb-financeiro anp-combustiveis aneel-tarifas anatel-banda-larga anac-aerodromos
        tomtom-transito osm-malha-capitais osm-malha-pbf ibge-malha-municipios ibge-malhas ibge-municipios malha-comparar
        indicador-arquivo""",
    "relatorios": "coletor-ingestao",
    "premios": "",
    "comparar": "",
}

_POR_TAREFA = {tarefa: cat for cat, texto in MAPA.items() for tarefa in texto.split()}


def categoria_de(tarefa: str) -> str:
    """Tarefa sem categoria escrita cai em Relatórios e Dados (o teste garante que nenhuma fica sem categoria)."""
    return _POR_TAREFA.get(tarefa, "relatorios")
