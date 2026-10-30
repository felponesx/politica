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
| tse-contas (gastos de campanha) | TSE (prestação de contas; 2002–2026, o nome do zip muda: 2012/2014 `prestacao_final_`, 2018+ `prestacao_de_contas_eleitorais_candidatos_`) | receitas por origem, despesas por tipo e por fornecedor (só CNPJ) | não | Leiautes de 2002, 2006, 2010, 2012, 2014, 2016 e 2022/SP conferidos com os arquivos reais; 2008, 2018, 2020, 2024 e 2026 usam os mesmos leiautes (2008 e 2018+ não conferidos linha a linha) | 2004 não traz o código do candidato (não dá para ligar); só candidaturas já coletadas; despesas declaradas ≠ pagas; zips de 14 MB a 1,4 GB |
| tse-candidatos, -resultados, -bens | TSE (dadosabertos.tse.jus.br, cdn.tse.jus.br) | candidatos, resultados, patrimônio, contas | não | Validada (2018–2026) | dados abertos só de 1994 em diante; TSE 2002 marca todos como eleitos |
| legislacao-normas | Senado (base de normas) | leis e decretos federais | não | Validada | LexML bloqueado fora do Brasil |
| lexml-estaduais | LexML | normas estaduais | não | Bloqueada fora do Brasil/para robôs | — |
| assembleias, assembleia-arquivo | ALESP, ALMG e outras | deputados estaduais | não | Parcial (ALMG bloqueada para robôs) | — |
| bcb-series, bcb-scr-estados | Banco Central (SGS, SCR.data) | séries econômicas desde 1985, crédito por UF | não | Validada | página HTML de erro tratada |
| bcb-financeiro | Banco Central — IF.data (Olinda) e SGS | balanço e resultado de bancos, cooperativas e financeiras; crédito, juros, spread e inadimplência | não | Validada contra a fonte real (26/10/2026, uma carga de teste) | o resultado do IF.data é semestral (soma de junho e dezembro); sem número de funcionários; a "receita" é a soma das rendas de crédito, títulos, serviços e tarifas (não é a contabilidade de uma empresa comum) |
| cnpj-fornecedores | BrasilAPI / minhareceita | cadastro e sócios | não | Validada (reserva incluída) | 1 consulta/s |
| pgfn-divida-ativa | PGFN | dívida ativa da União | não | **Não rodada** | arquivos grandes, trimestrais |
| desastres | Defesa Civil (planilhas) | desastres | não | **Não rodada** | carga manual por planilha |
| seguranca-prisional, -anuario, -sinesp, -efetivo, isp-rj-batalhoes | Senappen/Sisdepen, FBSP, Sinesp, ISP-RJ | prisões, crimes, efetivo, batalhões RJ | não | Validada | Procurados (BNMP/CNJ) bloqueado fora do Brasil; ISP-RJ é "na área", não "pelo" batalhão |
| saude-ubs, saude-mais-medicos | Ministério da Saúde (apidadosabertos.saude.gov.br) | UBS do CNES por município; vagas do Mais Médicos por município | não | Validada (30/10/2026, API real: 46.848 UBS em 5.481 municípios; 5.571 municípios do Mais Médicos, data 09/10/2026) | contar unidades não mede qualidade; Mais Médicos são só as vagas do programa. **Leitos hospitalares NÃO entram**: `cnes-leitos` devolve 1 linha por chamada (o `limit` é ignorado) e `hospitais-e-leitos` mistura todos os meses sem dizer qual é qual (não dá para pegar o mais recente); o filtro `uf` dessa rota dá erro 500. Ao SICONFI falta o Anexo 12 (mínimo constitucional em saúde): a API responde vazio para `RREO-Anexo 12` e `RREO-Anexo 08` |
| noticias-politica (+ robô de 15 min) | RSS de veículos | títulos e resumos | não | Validada | não são dados oficiais; sempre com link do veículo |
| contadores (impostômetro / gastômetro) | ACSP / CACB (gastobrasil.com.br) e conta própria | contadores | não | Validada (leitura ao vivo) | números de terceiros; divisão federal × estados+municípios é a do Impostômetro |
| Pesquisa na internet da IA | Perplexity (Agent e Search API) | respostas/links | **sim** | **Configurada, não testada** (sem chave no ambiente de desenvolvimento) | custo por chamada; ver limites em `docs/RELATORIO_AUDITORIA.md` |
| Propostas de governo | TSE (proposta_governo_AAAA_UF.zip) | PDFs → trechos por tema | não | Validada | PDF digitalizado fica `legivel: false`; resumo por trechos, sem conferir cumprimento |

Regras comuns a todos os coletores (`app/http.py`, `app/collectors/base.py`): timeout, retentativas com espera progressiva e
aleatória para 429/5xx respeitando `Retry-After`, barreira de rede interna (SSRF) em cada requisição e redirecionamento, upsert
idempotente com chave única (fonte, tipo, chave original) e `atualizado_em`, trava por tarefa no Postgres (a mesma coleta não roda
duas vezes ao mesmo tempo), coletas "rodando" há mais de 12 h viram `abortada`, e dados antigos nunca são apagados quando a fonte falha.

## Processos e casos de parlamentares (verificado em 23/10/2026, pelos servidores do GitHub)
| Fonte | O que foi confirmado | Uso no BRASIL+ |
|---|---|---|
| Câmara — representações por quebra de decoro (tipo `REP` em `/proposicoes`) | API aberta; a ementa nomeia o deputado ("em desfavor do Senhor Deputado …") | **Usada** (aba Processos; liga só por nome parlamentar único) |
| TSE — situação do registro de candidatura (`consulta_cand`) | já coletada (`DS_SITUACAO_CANDIDATURA`) | **Usada** (candidaturas não deferidas) |
| Casos curados do BRASIL+ (`app/dados/escandalos`) | fonte e data em cada situação | **Usada** (só nome completo igual ao da candidatura, sem homônimo) |
| STF — portal e Corte Aberta | o portal abre, mas a pesquisa por parte é página dinâmica (não é base aberta) e os painéis (`transparencia.stf.jus.br`) respondem 403 para robôs | **Não usada**: não há base aberta confirmada de inquéritos/ações penais de parlamentares |
| DataJud (CNJ) — API pública | a própria wiki diz: metadados de processos **públicos**, "resguardo de processos sigilosos e dados de partes"; consulta por número do processo, chave pública do CNJ | **Não usada**: não busca por nome e não traz partes; só serviria para enriquecer um número de processo já conhecido |
| TSE dados abertos (CKAN) | busca "processo": 8 conjuntos (resultados e afins, nenhum de processos contra candidatos); "inelegibilidade": 0 | **Não usada** |
| JusBrasil e similares | agregadores privados, sem API aberta, termos de uso restritivos | **Descartados** |
