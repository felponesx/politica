"""Categorias das fontes para o painel: cada coleta do BRASIL+ cai em um tema, e cada tema tem um ícone próprio.

Cada tarefa do coletor (`app/collectors/TAREFAS`) aparece em uma categoria. Tarefa nova sem categoria cai em "outras" e o teste
`tests/test_categorias.py` avisa para ela ganhar uma categoria de verdade.
"""

CATEGORIAS = [
    {"id": "congresso", "nome": "Congresso"},
    {"id": "eleicoes", "nome": "Eleições"},
    {"id": "gastos", "nome": "Gastos públicos"},
    {"id": "economia", "nome": "Economia"},
    {"id": "dividas", "nome": "Dívidas e empresas"},
    {"id": "justica", "nome": "Justiça"},
    {"id": "saude_educacao", "nome": "Saúde e educação"},
    {"id": "social", "nome": "Social e trabalho"},
    {"id": "seguranca", "nome": "Segurança"},
    {"id": "ambiente", "nome": "Meio ambiente e cidades"},
    {"id": "noticias", "nome": "Notícias"},
    {"id": "outras", "nome": "Outras"},
]

MAPA = {
    "congresso": """camara-deputados camara-orgaos camara-orientacoes camara-proposicoes camara-proposicoes-detalhe
        camara-proposicoes-situacao camara-tramitacoes camara-votacoes senado-senadores senado-votacoes senado-situacao
        senado-materias congresso-agenda congresso-atuacao congresso-cpis assembleias assembleia-arquivo lexml-estaduais
        legislacao-normas""",
    "eleicoes": "tse-bens tse-candidatos tse-resultados tse-doadores tse-fundos tse-contas",
    "gastos": """camara-despesas senado-ceaps transparencia-cartao transparencia-emendas transparencia-gastos
        transparencia-gastos-todos transparencia-orcamento transparencia-orgaos transparencia-contratos transparencia-viagens
        transparencia-servidores pncp-contratos obrasgov-obras siconfi-receitas siconfi-despesas-funcao siconfi-tributos
        tesouro-transferencias receita-arrecadacao receita-renuncia-fiscal reforma-tributaria receita-cbs cgibs-ibs""",
    "economia": """bcb-series bcb-financeiro ibge-indicadores ibge-empresas-economia anp-combustiveis aneel-tarifas
        anatel-banda-larga""",
    "dividas": """siconfi-divida pgfn-divida-ativa bcb-scr-estados tesouro-capag receita-empresas-porte
        receita-recuperacao-judicial cnpj-fornecedores""",
    "justica": "cnj-justica tcu-inabilitados tcu-contas-irregulares cgu-sancoes mte-lista-suja escandalos-fila ibama-multas",
    "saude_educacao": "saude-ubs saude-mais-medicos saude-datasus ensino-ideb inep-igc inep-censo-ies",
    "social": """transparencia-social ibge-trabalho ibge-indicadores-sociais ibge-saneamento caged-saldos
        caged-estoque-referencia""",
    "seguranca": "seguranca-anuario seguranca-efetivo seguranca-prisional seguranca-sinesp isp-rj-batalhoes prf-acidentes",
    "ambiente": """inpe-desmatamento inpe-prodes-mata-atlantica inpe-queimadas mapbiomas-alertas mapbiomas-alertas-territorio
        anac-aerodromos tomtom-transito osm-malha-capitais osm-malha-pbf ibge-malha-municipios ibge-malhas ibge-municipios
        malha-comparar desastres""",
    "noticias": "noticias-politica querido-diario",
    "outras": "coletor-ingestao indicador-arquivo",
}

_POR_TAREFA = {tarefa: cat for cat, texto in MAPA.items() for tarefa in texto.split()}


def categoria_de(tarefa: str) -> str:
    return _POR_TAREFA.get(tarefa, "outras")
