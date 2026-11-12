# Cobertura das 50 perguntas de treinamento da IA do BRASIL+

Regra fundamental: **nunca inventar**, **não tratar investigação como condenação** e **não confundir a ausência de registro no banco com a inexistência de processo ou atividade parlamentar**. Quando o dado não existe, a IA diz isso.

- **Dado nas fontes abertas:** 8 completo, 33 parcial, 9 sem dado.
- **IA própria:** 42 já respondem, 8 a fazer.

Fonte desta tabela: `app/dados/ia_cobertura.json` (também em `GET /ia/cobertura`). Um teste faz cada pergunta marcada como "responde" e confere que o motor a entende como aqui está.


## Identificação e perfil

| # | Pergunta | Dado | IA | Fonte | O que NÃO cobre |
|-|-|-|-|-|-|
| 1 | Quem é [nome] e qual cargo ocupa atualmente? | completo | responde | Cadastro da Câmara e do Senado. | Só mandatos no Congresso; cargos do Executivo e de tribunais não estão no cadastro. |
| 2 | Qual é o histórico político de [nome]? | parcial | responde | TSE: candidaturas e resultados (1994 em diante) ligadas ao parlamentar. | Só o que passou por eleição; cargos nomeados, suplência e mandatos anteriores a 1994 não aparecem. |
| 3 | Quais cargos públicos [nome] já ocupou? | parcial | responde | TSE (candidaturas e resultado) e cadastro do Congresso. | Só cargos de eleição; nomeados (ministro, secretário), suplentes que assumiram e vereadores não entram. |
| 4 | A qual partido [nome] pertence atualmente e por quais partidos já passou? | parcial | responde | Partido atual: cadastro. Anteriores: partido de cada candidatura no TSE. | Troca de partido fora de ano de eleição não aparece. |
| 5 | Qual é a formação acadêmica e profissional de [nome]? | parcial | responde | TSE: grau de instrução e ocupação declarados a cada candidatura. | É o que a própria pessoa declarou; não há diploma nem currículo. |
| 6 | Qual foi o patrimônio declarado por [nome] nas últimas eleições? | completo | responde | TSE: bens declarados a cada candidatura. | Valor declarado, sem correção pela inflação; só em ano de candidatura. |
| 7 | Quais são os principais projetos de lei apresentados por [nome]? | parcial | responde | Câmara e Senado: tramitação das proposições. | A autoria só existe para proposições com tramitação coletada; não há critério de projeto 'principal'. |
| 8 | Quais são as principais decisões e atuações políticas de [nome]? | parcial | responde | Votações nominais, presença, projetos e comissões. | 'Decisões' não existe como dado: o BRASIL+ mostra votos, presença e projetos. |
| 9 | Quem são os políticos que atualmente ocupam os principais cargos do governo federal? | sem dado | responde | — | A lista de ministros fica só no site, não no banco; não há base aberta única e atualizada de cargos do Executivo. |
| 10 | Quais políticos representam cada estado no Senado e na Câmara dos Deputados? | completo | responde | Cadastro da Câmara e do Senado. | Só quem está em exercício na última coleta. |

## Processos judiciais e investigações

| # | Pergunta | Dado | IA | Fonte | O que NÃO cobre |
|-|-|-|-|-|-|
| 11 | Quantos processos judiciais estão associados a [nome]? | sem dado | responde | — | Não existe base aberta de processos por pessoa. Existem só: representações por quebra de decoro (Câmara), registro de candidatura (TSE) e casos curados. |
| 12 | Quais políticos possuem registros de processos judiciais e quantos cada um possui? | parcial | responde | Casos curados do BRASIL+ (cada um com fonte). | Só os casos curados, e a lista mostra condenações: não é o total de processos de ninguém. |
| 13 | Quais processos de [nome] ainda estão em andamento? | parcial | responde | Casos curados e representações da Câmara. | Mostra a situação e a data da fonte; o andamento atual não é acompanhado. |
| 14 | Quais processos de [nome] já foram arquivados ou encerrados? | parcial | responde | Casos curados e representações da Câmara. | Só o que a fonte curada registra (ex.: 'processo arquivado', 'prescrito'). |
| 15 | [Nome] possui condenações judiciais? Quais são e qual é a situação atual? | parcial | responde | Casos curados do BRASIL+. | Só condenações dos casos curados; ausência aqui não prova que não existe. |
| 16 | Quais políticos possuem processos relacionados a improbidade administrativa? | sem dado | a fazer | — | Não há base aberta de ações de improbidade por pessoa; só apareceria se um caso curado descrevesse isso. |
| 17 | Existem investigações envolvendo [nome] em tribunais ou órgãos de controle? | parcial | responde | Casos curados; TCU (só totais, sem nome). | Só casos curados (situação e data da fonte); o TCU é publicado apenas em totais por estado, sem nome. |
| 18 | Em quais tribunais existem processos associados a [nome]? | sem dado | responde | — | Não existe base aberta que diga em quais tribunais uma pessoa responde. |
| 19 | Quanto tempo os processos envolvendo [nome] estão em tramitação? | sem dado | responde | — | Não existe base aberta com o tempo de tramitação de processos por pessoa. |
| 20 | Quais políticos possuem condenações definitivas, distinguindo-as de investigações e processos ainda sem decisão final? | parcial | responde | Casos curados do BRASIL+ (situação com termos fechados). | Distingue 'condenado' de 'condenado (recorre)' (ainda cabe recurso); investigados e réus não entram nessa lista. |

## Projetos de lei

| # | Pergunta | Dado | IA | Fonte | O que NÃO cobre |
|-|-|-|-|-|-|
| 21 | Quantos projetos de lei [nome] apresentou durante seu mandato? | parcial | responde | Câmara e Senado: tramitação. | Só entre as proposições com tramitação coletada: número menor não quer dizer que apresentou pouco. |
| 22 | Quantos projetos de lei foram aprovados, rejeitados ou arquivados? | parcial | a fazer | Situação registrada de cada proposição. | Para uma pessoa funciona (perguntas 21, 24 e 25); a versão geral, sem nome, ainda não existe. |
| 23 | Quais parlamentares possuem registros de projetos apresentados e quantos cada um possui? | parcial | a fazer | Tramitação coletada. | Só proposições com tramitação coletada. |
| 24 | Quais projetos de [nome] já se transformaram em leis? | parcial | responde | Situação 'transformado em norma jurídica'. | Só entre as proposições com tramitação coletada. |
| 25 | Quantos projetos apresentados por [nome] ainda estão aguardando votação? | parcial | responde | Situação registrada. | Conta 'em andamento ou sem decisão final'; não separa quem já está pautado. |
| 26 | Quais deputados e senadores apresentaram projetos nos últimos 12 meses? | parcial | a fazer | Tramitação coletada e data de apresentação. | Só proposições com tramitação coletada. |
| 27 | Quantos projetos [nome] apresentou como autor e como coautor? | parcial | responde | — | Mostra as proposições em que a pessoa consta entre os autores; não separa autor principal de coautor. |
| 28 | Quais áreas são mais abordadas nos projetos apresentados por [nome]? | parcial | responde | Ementa das proposições com tramitação coletada. | Áreas por palavra-chave da ementa; não é posição política. |
| 29 | Quais projetos de [nome] tiveram impacto financeiro previsto no orçamento público? | sem dado | responde | — | O impacto financeiro previsto por proposição não é publicado como dado aberto. |
| 30 | Como a produção legislativa de [nome] se compara à de outros parlamentares do mesmo período? | parcial | responde | Cota e votações nominais. | A comparação de projetos não é feita: a autoria é coletada só em parte. Compara cota e participação em votações. |

## Votações e participação

| # | Pergunta | Dado | IA | Fonte | O que NÃO cobre |
|-|-|-|-|-|-|
| 31 | Quantas votações nominais [nome] participou durante o mandato? | parcial | responde | Votações nominais coletadas. | Últimos 12 meses (presença) e votos nas votações coletadas; não é o mandato inteiro. |
| 32 | Em quantas votações [nome] esteve ausente? | parcial | responde | Votações nominais coletadas. | Ausência é calculada (total menos votou) e inclui licença e quem ainda não tinha tomado posse. |
| 33 | Quantas vezes [nome] votou a favor, contra ou se absteve? | completo | responde | Votos nas votações nominais coletadas. | Só votações nominais coletadas; votação secreta não entra. |
| 34 | Quais parlamentares possuem registros de maior participação em votações nominais? | completo | responde | Votações nominais dos últimos 12 meses. | Só quem está em exercício; suplente recente aparece com menos votações. |
| 35 | Quais parlamentares possuem registros de menor participação em votações nominais? | parcial | responde | Votações nominais dos últimos 12 meses. | Quem não votou em nenhuma não aparece na lista. |
| 36 | Como [nome] votou nas principais propostas relacionadas à economia? | parcial | a fazer | Votos + ementa da matéria. | Exigiria classificar votações por tema por palavra-chave; 'principais' não é critério do dado. |
| 37 | Como [nome] votou em projetos relacionados à saúde e educação? | parcial | a fazer | Votos + ementa da matéria. | Idem: classificação por palavra-chave. |
| 38 | Qual foi o posicionamento de [nome] nas votações de reformas tributárias e previdenciárias? | parcial | a fazer | Votos + nome da matéria. | Só se a votação estiver coletada e identificável pelo nome da proposição. |
| 39 | Como mudou o comportamento de votação de [nome] ao longo dos anos? | parcial | a fazer | Votos por ano. | Depende de quantos anos de votações foram coletados. |
| 40 | Como votaram individualmente os ministros do STF, STJ e TSE em determinada decisão? | sem dado | responde | — | Não há base aberta com o voto de cada ministro; só 6 julgamentos do STF curados, com placar. |

## Gastos, patrimônio e atividade

| # | Pergunta | Dado | IA | Fonte | O que NÃO cobre |
|-|-|-|-|-|-|
| 41 | Quanto [nome] recebeu de remuneração durante o mandato? | sem dado | responde | — | A remuneração por pessoa não é coletada; a cota parlamentar não é salário. |
| 42 | Quanto [nome] gastou com verba parlamentar? | completo | responde | Cota parlamentar (Câmara e Senado). | Valor reembolsado/pago; ano corrente pode estar incompleto. |
| 43 | Quais foram as principais despesas de [nome] com viagens, hospedagens e passagens? | parcial | responde | Categorias da cota parlamentar. | Só o que a cota reembolsa; viagens pagas por outros meios não aparecem. |
| 44 | Quais políticos possuem registros de despesas parlamentares e quais são os valores por categoria? | completo | responde | Cota parlamentar por categoria. | As categorias têm nomes diferentes na Câmara e no Senado. |
| 45 | Quanto [nome] recebeu em doações eleitorais e quais foram seus principais doadores? | parcial | responde | TSE: prestação de contas (origem das receitas, despesas por tipo). | O nome de cada doador pessoa física não é guardado (CPF não é guardado). |
| 46 | Qual foi a evolução do patrimônio declarado de [nome] entre as eleições? | completo | responde | TSE: bens declarados. | Sem correção pela inflação. |
| 47 | Quantas emendas parlamentares [nome] apresentou e quais valores foram destinados? | parcial | responde | Portal da Transparência: emendas. | Só os 30 maiores autores de cada ano; o número de emendas por pessoa não é guardado. |
| 48 | Quanto das emendas de [nome] foi efetivamente empenhado, liquidado e pago? | parcial | responde | Portal da Transparência: emendas. | Por autor há empenhado e pago; o liquidado existe só no total do ano. |
| 49 | Quais empresas receberam recursos públicos relacionados a contratos ou emendas indicadas por [nome]? | sem dado | responde | — | O vínculo entre cada emenda e a empresa que recebeu não é coletado. |
| 50 | Como se distribuem os gastos, a participação legislativa, os projetos e as votações de [nome] em comparação com outros políticos do mesmo cargo e período? | parcial | responde | Cota e votações nominais. | Projetos e emendas ficam fora da comparação (coletados só em parte). |
