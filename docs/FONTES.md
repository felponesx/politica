# Inventário de fontes e coletores (BRASIL+)

Estado = o que está **comprovado**, não o que está configurado. "Validada" = rodou contra a fonte real (robô do GitHub Actions,
09/10/2026, ver README) e gravou dados. "Configurada, não testada" = o código existe e passa nos testes com respostas de exemplo,
mas nunca foi conferido contra a fonte real. O estado vivo de cada tarefa (última coleta boa, idade, erro) está em `GET /fontes/status`
e na tela **Relatórios e Dados › Situação das fontes**.

| Tarefa(s) | Fonte / órgão | Dado | Chave? | Estado | Limitações conhecidas |
|---|---|---|---|---|---|
| camara-deputados, -proposicoes, -votacoes, -despesas, -orgaos, -tramitacoes, -proposicoes-situacao | Câmara dos Deputados (dadosabertos.camara.leg.br) | deputados, projetos, votações, cota, situação | não | Validada | cota: arquivo anual; votação simbólica sem voto individual (404 tratado) |
| senado-senadores, -votacoes, -materias, -ceaps | Senado Federal (legis.senado.leg.br, adm.senado.gov.br) | senadores, votações, matérias, CEAPS | não | Validada | máx. 60 dias por consulta; votação secreta usa só o placar oficial |
| congresso-agenda, congresso-atuacao | Câmara e Senado | agenda do dia, atuação | não | Validada | — |
| ibge-municipios, ibge-indicadores(-sociais), ibge-malhas, ibge-saneamento, ibge-empresas-economia | IBGE (servicodados.ibge.gov.br, SIDRA) | municípios, indicadores, mapas, saneamento (Censo 2022), economia de empresas | não | Validada (saneamento e empresas: dados reais publicados) | pessoas = % × população (estimativa); sem faturamento por empresa em base aberta |
| siconfi-receitas, -divida, -despesas-funcao, -tributos | Tesouro Nacional (SICONFI) | receitas, dívida, despesa por função, tributos (RREO) | não | Validada | prefeituras sem relatório são estimadas pela média por habitante (sinalizado) |
| tesouro-transferencias, tesouro-capag | Tesouro Nacional | transferências, CAPAG | não | Validada | — |
| receita-arrecadacao, receita-empresas-porte, receita-recuperacao-judicial | Receita Federal (gov.br/receitafederal), CNPJ aberto | arrecadação por UF, empresas por porte, recuperação judicial | não | Validada | porte "Demais" junta médias e grandes (a Receita não separa) |
| pncp-contratos | PNCP | contratos | não | Validada | — |
| transparencia-orgaos/-contratos/-gastos(-todos) | Portal da Transparência (CGU) | órgãos, contratos, gastos | **sim** | Configurada, não testada | ~90 req/min; sem a chave, as telas usam `transparencia-orcamento` |
| transparencia-orcamento | Portal da Transparência (arquivo anual) | orçamento por órgão | não | Validada | — |
| obrasgov-obras | ObrasGov (Ministério da Gestão) | obras com dinheiro federal | não | Validada | % de execução física por obra não é aberto |
| tse-candidatos, -resultados, -bens, -contas | TSE (dadosabertos.tse.jus.br, cdn.tse.jus.br) | candidatos, resultados, patrimônio, contas | não | Validada (2018–2026) | dados abertos só de 1994 em diante; TSE 2002 marca todos como eleitos |
| legislacao-normas | Senado (base de normas) | leis e decretos federais | não | Validada | LexML bloqueado fora do Brasil |
| lexml-estaduais | LexML | normas estaduais | não | Bloqueada fora do Brasil/para robôs | — |
| assembleias, assembleia-arquivo | ALESP, ALMG e outras | deputados estaduais | não | Parcial (ALMG bloqueada para robôs) | — |
| bcb-series, bcb-scr-estados | Banco Central (SGS, SCR.data) | séries econômicas desde 1985, crédito por UF | não | Validada | página HTML de erro tratada |
| cnpj-fornecedores | BrasilAPI / minhareceita | cadastro e sócios | não | Validada (reserva incluída) | 1 consulta/s |
| pgfn-divida-ativa | PGFN | dívida ativa da União | não | **Não rodada** | arquivos grandes, trimestrais |
| desastres | Defesa Civil (planilhas) | desastres | não | **Não rodada** | carga manual por planilha |
| seguranca-prisional, -anuario, -sinesp, -efetivo, isp-rj-batalhoes | Senappen/Sisdepen, FBSP, Sinesp, ISP-RJ | prisões, crimes, efetivo, batalhões RJ | não | Validada | Procurados (BNMP/CNJ) bloqueado fora do Brasil; ISP-RJ é "na área", não "pelo" batalhão |
| noticias-politica (+ robô de 15 min) | RSS de veículos | títulos e resumos | não | Validada | não são dados oficiais; sempre com link do veículo |
| contadores (impostômetro / gastômetro) | ACSP / CACB (gastobrasil.com.br) e conta própria | contadores | não | Validada (leitura ao vivo) | números de terceiros; divisão federal × estados+municípios é a do Impostômetro |
| Pesquisa na internet da IA | Perplexity (Agent e Search API) | respostas/links | **sim** | **Configurada, não testada** (sem chave no ambiente de desenvolvimento) | custo por chamada; ver limites em `docs/RELATORIO_AUDITORIA.md` |
| Propostas de governo | TSE (proposta_governo_AAAA_UF.zip) | PDFs → trechos por tema | não | Validada | PDF digitalizado fica `legivel: false`; resumo por trechos, sem conferir cumprimento |

Regras comuns a todos os coletores (`app/http.py`, `app/collectors/base.py`): timeout, retentativas com espera progressiva e
aleatória para 429/5xx respeitando `Retry-After`, barreira de rede interna (SSRF) em cada requisição e redirecionamento, upsert
idempotente com chave única (fonte, tipo, chave original) e `atualizado_em`, trava por tarefa no Postgres (a mesma coleta não roda
duas vezes ao mesmo tempo), coletas "rodando" há mais de 12 h viram `abortada`, e dados antigos nunca são apagados quando a fonte falha.
