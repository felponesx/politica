# Ordem de ligação das fontes (do mais leve ao mais pesado)

Tamanhos são **estimativas** tiradas das notas do projeto (`CLAUDE.md`, `docs/FONTES.md`). Não medi cada arquivo agora, porque o
ambiente de trabalho não alcança os sites do governo. Antes de ligar uma fonte, o coletor do celular mede o tamanho real e registra.

## Lote 1 — leves (KB a poucos MB, API ou CSV pequeno)
1. `bcb-series` — séries do Banco Central (KB por série). **Já ligada** (adaptador `bcb`).
2. `camara-deputados` — lista de deputados (JSON paginado, centenas de KB). Mapa `linhas` com `lista = "dados"`.
3. `senado-senadores` — lista de senadores (KB).
4. `tcu-inabilitados` — só totais por estado e ano (KB).
5. `noticias-politica` — feeds RSS (KB). Já tem robô próprio a cada 15 min; a ligação aqui é só para o histórico.

## Lote 2 — médios (dezenas de MB)
6. `camara-proposicoes-situacao` — arquivo anual de proposições.
7. `camara-orientacoes` — orientações de bancada, arquivo anual.
8. `anp-combustiveis` — preço por estado (zip semestral).
9. `cnj-justica` — fila dos tribunais (zip).
10. `cgu-sancoes` — empresas punidas (zip diário).
11. `transparencia-viagens`, `ibge-trabalho`, `aneel-tarifas` — tabelas mensais ou anuais.

## Lote 3 — pesados (centenas de MB ou mais)
12. `prf-acidentes` — CSV por ano (dezenas de MB).
13. `tse-fundos`, `tse-resultados` — arquivos grandes por eleição.
14. `transparencia-servidores` — zip mensal de ~83 MB.
15. `caged-saldos` — microdados em 7z de ~50 MB por mês.
16. `inep-censo-ies` — ~457 MB.
17. `inpe-prodes-mata-atlantica` — shapefile de ~472 MB.
18. `ibge-malha-municipios` — ~237 MB.
19. `osm-malha-pbf` — extratos regionais de 160 a 860 MB.
20. `anatel-banda-larga` — zip de ~1 GB (lido por trechos).
21. `receita-empresas-porte` — base mensal do CNPJ (gigabytes).
22. `transparencia-social` — dezenas de milhões de linhas.

## Regra para não precisar de aprovação
- Dado que passa nas regras e no Gemini é publicado sozinho.
- Dado suspeito fica de lado e o último dado bom continua no ar. Nada para o usuário fazer.
- Na próxima coleta o dado é verificado de novo. Se vier bom, entra sozinho.
- Só falhas técnicas (rede, formato mudou) aparecem na tela de situação, como aviso, nunca como pedido de ação.
