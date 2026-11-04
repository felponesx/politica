# Vínculos do BRASIL+ pelo celular

Gerado por `python -m scripts.inventario_vinculos`. Uma linha por tarefa de coleta do BRASIL+.

## Como uma fonte se liga
1. No vínculo do celular (`vinculos/<produto>.toml`), a fonte declara `adaptador` e `mapa`, ou usa adaptador próprio.
2. O coletor do celular baixa, confere, corrige só o formato e publica `dados/<fonte>/atual` + `meta.json` (com o `mapa`).
3. O BRASIL+ lê o `meta.json` (`coletor-ingestao`), confere o hash e grava em `registros` pelo mapa.
4. Sem adaptador declarado e sem adaptador próprio, a fonte é ignorada. Adaptador declarado e inexistente é erro.

Mapa genérico (`adaptador = "linhas"`): `tipo`, `chave` (obrigatório), `valor`, `titulo`, `uf`, `data`, e `dados` (campos extras), com caminhos pontilhados como `orgao.nome`.

## Tarefas

| Tarefa | Grava em `coletas` | Caminho pelo celular |
|---|---|---|
| `anac-aerodromos` | anac / aerodromos | pendente: falta o vínculo pelo celular |
| `anatel-banda-larga` | anatel / banda_larga | pendente: falta o vínculo pelo celular |
| `aneel-tarifas` | aneel / tarifas | pendente: falta o vínculo pelo celular |
| `anp-combustiveis` | anp / combustiveis | pendente: falta o vínculo pelo celular |
| `assembleia-arquivo` | assembleias / deputados_arquivo | pendente: falta o vínculo pelo celular |
| `assembleias` | assembleias / deputados_votacoes | pendente: falta o vínculo pelo celular |
| `bcb-financeiro` | bcb / financeiro | pendente: falta o vínculo pelo celular |
| `bcb-scr-estados` | bcb / scr_uf | pendente: falta o vínculo pelo celular |
| `bcb-series` | bcb / series | adaptador próprio (`bcb`), testado |
| `caged-estoque-referencia` | caged / estoque_referencia | pendente: falta o vínculo pelo celular |
| `caged-saldos` | caged / saldos | pendente: falta o vínculo pelo celular |
| `camara-deputados` | camara / deputados | pendente: falta o vínculo pelo celular |
| `camara-despesas` | camara / despesas | pendente: falta o vínculo pelo celular |
| `camara-orgaos` | camara / orgaos | pendente: falta o vínculo pelo celular |
| `camara-orientacoes` | camara / orientacoes | pendente: falta o vínculo pelo celular |
| `camara-proposicoes` | camara / proposicoes | pendente: falta o vínculo pelo celular |
| `camara-proposicoes-detalhe` | camara / proposicoes_detalhe | pendente: falta o vínculo pelo celular |
| `camara-proposicoes-situacao` | camara / proposicoes_situacao | pendente: falta o vínculo pelo celular |
| `camara-tramitacoes` | camara / tramitacoes | pendente: falta o vínculo pelo celular |
| `camara-votacoes` | camara / votacoes | pendente: falta o vínculo pelo celular |
| `cgibs-ibs` | cgibs / ibs_monitor | pendente: falta o vínculo pelo celular |
| `cgu-sancoes` | cgu / sancoes | pendente: falta o vínculo pelo celular |
| `cnj-justica` | cnj / justica_em_numeros | pendente: falta o vínculo pelo celular |
| `cnpj-fornecedores` | receita / cnpj_fornecedores | pendente: falta o vínculo pelo celular |
| `coletor-ingestao` | coletor / ingestao | pendente: falta o vínculo pelo celular |
| `congresso-agenda` | congresso / agenda | pendente: falta o vínculo pelo celular |
| `congresso-atuacao` | congresso / atuacao | pendente: falta o vínculo pelo celular |
| `congresso-cpis` | congresso / cpis | pendente: falta o vínculo pelo celular |
| `desastres` | defesacivil / desastres | pendente: falta o vínculo pelo celular |
| `ensino-ideb` | inep / ideb | pendente: falta o vínculo pelo celular |
| `escandalos-fila` | escandalos / fila | pendente: falta o vínculo pelo celular |
| `ibama-multas` | ibama / multas | pendente: falta o vínculo pelo celular |
| `ibge-empresas-economia` | ibge / empresas_economia | pendente: falta o vínculo pelo celular |
| `ibge-indicadores` | ibge / indicadores | pendente: falta o vínculo pelo celular |
| `ibge-indicadores-sociais` | ibge / indicadores_sociais | pendente: falta o vínculo pelo celular |
| `ibge-malha-municipios` | ibge / malha_municipal | pendente: falta o vínculo pelo celular |
| `ibge-malhas` | ibge / malhas | pendente: falta o vínculo pelo celular |
| `ibge-municipios` | ibge / municipios | pendente: falta o vínculo pelo celular |
| `ibge-saneamento` | ibge / saneamento | pendente: falta o vínculo pelo celular |
| `ibge-trabalho` | ibge / trabalho | pendente: falta o vínculo pelo celular |
| `indicador-arquivo` | arquivo / indicador | pendente: falta o vínculo pelo celular |
| `inep-censo-ies` | inep / censo_ies | pendente: falta o vínculo pelo celular |
| `inep-igc` | inep / igc | pendente: falta o vínculo pelo celular |
| `inpe-desmatamento` | inpe / desmatamento | pendente: falta o vínculo pelo celular |
| `inpe-prodes-mata-atlantica` | inpe / prodes_mata_atlantica | pendente: falta o vínculo pelo celular |
| `inpe-queimadas` | inpe / queimadas | pendente: falta o vínculo pelo celular |
| `isp-rj-batalhoes` | isp-rj / aisp | pendente: falta o vínculo pelo celular |
| `legislacao-normas` | senado / legislacao | pendente: falta o vínculo pelo celular |
| `lexml-estaduais` | lexml / normas_estaduais | pendente: falta o vínculo pelo celular |
| `malha-comparar` | malha / comparacao | pendente: falta o vínculo pelo celular |
| `mapbiomas-alertas` | mapbiomas / alertas_bioma | pendente: falta o vínculo pelo celular |
| `mapbiomas-alertas-territorio` | mapbiomas / alertas_territorio | pendente: falta o vínculo pelo celular |
| `mte-lista-suja` | mte / lista_suja | pendente: falta o vínculo pelo celular |
| `noticias-politica` | noticias / politica | pendente: falta o vínculo pelo celular |
| `obrasgov-obras` | obrasgov / obras | pendente: falta o vínculo pelo celular |
| `osm-malha-capitais` | osm / malha_capitais | pendente: falta o vínculo pelo celular |
| `osm-malha-pbf` | osm / malha_pbf | pendente: falta o vínculo pelo celular |
| `pgfn-divida-ativa` | pgfn / divida_ativa | pendente: falta o vínculo pelo celular |
| `pncp-contratos` | pncp / contratos | pendente: falta o vínculo pelo celular |
| `prf-acidentes` | prf / acidentes | pendente: falta o vínculo pelo celular |
| `querido-diario` | querido_diario / diarios | pendente: falta o vínculo pelo celular |
| `receita-arrecadacao` | receita / arrecadacao_estados | pendente: falta o vínculo pelo celular |
| `receita-cbs` | receita / cbs_monitor | pendente: falta o vínculo pelo celular |
| `receita-empresas-porte` | receita / empresas_porte | pendente: falta o vínculo pelo celular |
| `receita-recuperacao-judicial` | receita / recuperacao_judicial | pendente: falta o vínculo pelo celular |
| `receita-renuncia-fiscal` | receita / renuncia_fiscal | pendente: falta o vínculo pelo celular |
| `reforma-tributaria` | reforma / iva_monitor | pendente: falta o vínculo pelo celular |
| `saude-datasus` | datasus / saude | pendente: falta o vínculo pelo celular |
| `saude-mais-medicos` | saude / mais_medicos | pendente: falta o vínculo pelo celular |
| `saude-ubs` | saude / ubs | pendente: falta o vínculo pelo celular |
| `seguranca-anuario` | fbsp / anuario | pendente: falta o vínculo pelo celular |
| `seguranca-efetivo` | fbsp / efetivo | pendente: falta o vínculo pelo celular |
| `seguranca-prisional` | sisdepen / prisional | pendente: falta o vínculo pelo celular |
| `seguranca-sinesp` | sinesp / vde | pendente: falta o vínculo pelo celular |
| `senado-ceaps` | senado / ceaps | pendente: falta o vínculo pelo celular |
| `senado-materias` | senado / materias | pendente: falta o vínculo pelo celular |
| `senado-senadores` | senado / senadores | pendente: falta o vínculo pelo celular |
| `senado-situacao` | senado / situacao | pendente: falta o vínculo pelo celular |
| `senado-votacoes` | senado / votacoes | pendente: falta o vínculo pelo celular |
| `siconfi-despesas-funcao` | siconfi / despesas_funcao | pendente: falta o vínculo pelo celular |
| `siconfi-divida` | siconfi / divida_estados | pendente: falta o vínculo pelo celular |
| `siconfi-receitas` | siconfi / receitas_estados | pendente: falta o vínculo pelo celular |
| `siconfi-tributos` | siconfi / tributos_entes | pendente: falta o vínculo pelo celular |
| `tcu-contas-irregulares` | tcu / contas_irregulares | pendente: falta o vínculo pelo celular |
| `tcu-inabilitados` | tcu / inabilitados | pendente: falta o vínculo pelo celular |
| `tesouro-capag` | tesouro / capag_municipios | pendente: falta o vínculo pelo celular |
| `tesouro-transferencias` | tesouro / transferencias | pendente: falta o vínculo pelo celular |
| `tomtom-transito` | tomtom / transito | pendente: falta o vínculo pelo celular |
| `transparencia-cartao` | transparencia / cartao_corporativo | pendente: falta o vínculo pelo celular |
| `transparencia-contratos` | transparencia / contratos | pendente: falta o vínculo pelo celular |
| `transparencia-emendas` | transparencia / emendas_parlamentares | pendente: falta o vínculo pelo celular |
| `transparencia-gastos` | transparencia / gastos_orgao | pendente: falta o vínculo pelo celular |
| `transparencia-gastos-todos` | transparencia / gastos_orgao | pendente: falta o vínculo pelo celular |
| `transparencia-orcamento` | transparencia / orcamento_orgaos | pendente: falta o vínculo pelo celular |
| `transparencia-orgaos` | transparencia / orgaos_siafi | pendente: falta o vínculo pelo celular |
| `transparencia-servidores` | transparencia / servidores | pendente: falta o vínculo pelo celular |
| `transparencia-social` | transparencia / social | pendente: falta o vínculo pelo celular |
| `transparencia-viagens` | transparencia / viagens | pendente: falta o vínculo pelo celular |
| `tse-bens` | tse / bens | pendente: falta o vínculo pelo celular |
| `tse-candidatos` | tse / candidatos | pendente: falta o vínculo pelo celular |
| `tse-contas` | tse / contas_campanha | pendente: falta o vínculo pelo celular |
| `tse-doadores` | tse / doadores_cnpj | pendente: falta o vínculo pelo celular |
| `tse-fundos` | tse / fundos | pendente: falta o vínculo pelo celular |
| `tse-resultados` | tse / resultados | pendente: falta o vínculo pelo celular |
