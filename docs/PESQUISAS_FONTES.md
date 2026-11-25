# Pesquisas financiadas com dinheiro público — inventário de fontes (25/11/2026)

> **Atualização (25/11, tarde):** a aba Pesquisas está no ar com **FINEP, FAPEMIG e INT** (ver CLAUDE.md, "Pesquisas"). O diagnóstico pelo robô do GitHub (`diag-pesquisas.yml`) achou as planilhas abertas da
> FINEP (`https://download.finep.gov.br/Contratacao.xlsx`, `Liberacao.xlsx`, `Nao_Aprovados.xlsx`), que não abriam pela página legada daqui; a aba de projetos para ICTs traz contratado **e liberado** por projeto.
> O que o robô encontrou nas demais fontes está na seção "Resultado do diagnóstico pelo robô" no fim.

Etapa de **investigação** da aba "Pesquisas" (nada foi integrado ao banco nem ao site ainda). Cada linha abaixo foi testada daqui (ambiente do Claude na nuvem);
"não abriu daqui" não quer dizer que a fonte não existe: pode abrir pelo robô do GitHub (`diagnostico.yml`) ou de um computador no Brasil.

## Resultado em uma tabela

| Fonte | Situação | Projeto | Pesquisador | Instituição | Valor | Estado | Datas | Frequência |
|---|---|---|---|---|---|---|---|---|
| **FAPEMIG** (MG) | **Funciona.** 3 planilhas XLSX abertas | sim | sim (coordenador) | sim (executora e gestora) | sim (valor contratado) | só MG (cadastro de instituições traz o estado) | início e término | a cada 3 meses |
| **INT** (RJ, MCTI) | **Funciona.** XLSX por ano | sim (+ descrição) | não (só o cliente) | o próprio INT | sim (valor pactuado) | RJ | assinatura do contrato | anual |
| **CAPES** | Responde (CKAN), mas os conjuntos são de bolsas de ensino/formação, não de projetos | não | só bolsistas | sim | parcial | — | — | — |
| **Transferegov** | API responde; convênios com objeto, convenente e repasse | objeto | não | sim | sim | sim | sim | contínua |
| **CNPq** | Painéis agregados em Tableau (bi.cnpq.br) e Power BI; `dadosabertos.cnpq.br` não abriu; Base dos Dados exige BigQuery | no painel, agregado | não visto | agregado | agregado | agregado | — | — |
| **FINEP** | Site legado não abriu daqui; há painel Power BI de projetos contratados desde 2002 | sim (no painel) | não | sim | sim | sim | sim | — |
| **FAPERJ** | Busca por formulário (`siteantigo.faperj.br`), sem arquivo para baixar visto | a testar | a testar | a testar | a testar | RJ | — | — |
| **FAPESP** | Biblioteca Virtual (`bv.fapesp.br`) abre; é site de consulta, sem arquivo visto | sim | sim (Pesquisador Responsável) | sim (Instituição Sede) | "Apoio FAPESP em Números" | SP | sim | — |

Não investigadas ainda: as outras 22 fundações estaduais, EMBRAPII, Fiocruz, Butantan, Embrapa, INPE, INPA, LNCC, IBICT, IMPA, CBPF, CNPEM, IPEN, IPT, INMETRO, IPEA e as universidades.
Os pagamentos de cada instituição pelo Portal da Transparência também não foram testados nesta etapa.

## FAPEMIG (conferida com o arquivo real, baixado em 25/11/2026)

- Página: `https://fapemig.br/difusao-do-conhecimento/fapemig-em-numeros/dados-abertos-fapemig`. Também publicada no portal de dados da CGE-MG (`dados.mg.gov.br`). Plano de Dados Abertos 2023–2025.
- Arquivos (nome diz CSV, mas são **XLSX**): `https://api.site.fapemig.br/wp-content/uploads/projetos-contratados.xlsx` (3,6 MB), `bolsas-cotas-concedidas.xlsx` (5,7 MB), `instituicoescadastradas.xlsx` (167 KB). Publicação de 03/06/2026.
- `projetos-contratados`: 1 aba, **23.445 linhas, anos 2007 a 2026, soma de `valorcontratado` = R$ 4,13 bi**. Colunas: `ano`, `processo`, `coordenador`, `modalidade`, `chamada_num`, `chamada_desc`, `grupochamada`, `linha`, `titulo`, `area`,
  `camaraavaliacao`, `valorcontratado`, `instituicaoexecutora_sigla`, `instituicaoexecutora_nome`, `instituicaogestora_sigla`, `instituicaogestora_nome`, `data_inicio`, `data_termino`, `datadisponibilizacao`.
- Campos vazios: `titulo` 894, `camaraavaliacao` 2.844, `valorcontratado` 4, `area` 19, instituição executora 4 (sigla 23). Uma linha tem `ano = "RBE"` (não é ano). Os vazios têm que aparecer como "não informado", nunca como zero.
- Não tem estado nem município por projeto (o estado vem do cadastro de instituições, quando a instituição consta lá). É valor **contratado**, não pago.
- `instituicaogestora` costuma ser uma fundação de apoio (FUNDEP, FADENOR...): é quem administra o dinheiro, não quem pesquisa. A instituição de quem pesquisa é a `executora`.

## INT (conferida com arquivos reais de 2025)

- Página: `https://www.gov.br/int/pt-br/acesso-a-informacao/dados-abertos`. Arquivos por ano (2022 a 2025), em `.../acesso-a-informacao/arquivos/<ano>-lista-de-...xlsx/@@download/file`.
- Projetos de P&D contratados (cliente governo: 13 linhas em 2025; cliente empresa: 5): `N.`, `Título do Projeto`, `Descrição do Projeto`, `Data de Assinatura do Contrato`, `Valor Pactuado (R$)`, `Nome do Cliente/Razão Social`. Sem nome de pesquisador.
- É dinheiro que o INT **recebe** de clientes (governo e empresas), não bolsa nem auxílio. A lista de bolsistas existe (153 linhas, com nome, titulação, área e supervisor): é dado de pessoa e só entraria com a regra de nomes abaixo.
- Outras listas na página: acordos de cooperação, ativos de propriedade intelectual, publicações científicas, serviços tecnológicos contratados.

## CNPq

- `gov.br/cnpq/.../dados-abertos/paineis-de-dados`: Painel de Fomento em CT&I (`bi.cnpq.br`, Tableau Public), Painel de Bolsas e Projetos Vigentes, Painel Lattes, Painel de Demanda e Atendimento, Painel de Chamadas de Bolsas PQ, PIBIC/PIBITI (Power BI).
  São visualizações; não achei arquivo por projeto ou pesquisador. `dadosabertos.cnpq.br` e `.../consulta-de-dados-1` não abriram daqui.
- A Base dos Dados tem "Bolsas e Auxílios Pagos pelo CNPq" (2002–2022), mas o acesso é por BigQuery com conta Google; não conferi as colunas.

## FINEP, FAPERJ, FAPESP

- FINEP: `legacy.finep.gov.br/transparencia-finep/paineis-e-downloads/central-de-downloads` deu falha de conexão daqui; o "Consulta aos Projetos Contratados" é Power BI. Testar pelo robô.
- FAPERJ: o formulário de busca (`busca_projeto.phtml`) abre; falta testar se aceita pedido automático e que campos devolve (o "Resumo de projetos contemplados" está em `/?id=47.4.0`).
- FAPESP: a Biblioteca Virtual lista auxílios e bolsas com pesquisador e instituição, mas como páginas de consulta; falta ver se há exportação ou API.

## Fontes que só identificam (não dizem valor)

OpenAlex (`api.openalex.org` respondeu, 200) para instituições, pesquisadores e publicações; Plataforma Brasil (registra pesquisas com seres humanos, não financiamento); Lattes, BrCris, ORCID, SciELO, BDTD.
Nunca usar para inventar valor de financiamento.

## Regras para a coleta

- Valor é sempre do tipo que a fonte diz (contratado, pactuado, pago...), com o nome do tipo na tela. Não somar tipos diferentes. Valor ausente = "não informado".
- Nomes de pesquisadores: só o que a própria agência publica na base (FAPEMIG publica o coordenador), com o link da fonte; sem CPF, e-mail ou telefone; nunca ligar por nome parecido a outra base ou ao Lattes.
- Instituição executora × gestora: mostrar quem executa; a fundação de apoio aparece como "gestora".
- Projeto repetido entre fontes só é unido quando houver identificador igual (processo) — nunca só por título ou nome.
- Cada linha guarda fonte, arquivo, data da publicação e data da coleta. Arquivo original preservado.

## Proposta de próximo passo

1. Integrar **FAPEMIG** primeiro (é a única com projeto + coordenador + instituição + valor + datas em arquivo aberto): coletor `pesquisas-fapemig`, tabela própria, `GET /pesquisas`, aba "Pesquisas" com lista, filtros (instituição, área, ano, chamada) e ficha da instituição.
2. Rodar FINEP, CNPq, FAPERJ e FAPESP pelo robô de diagnóstico para ver o que responde de fora da nuvem do Claude.
3. Pagamentos federais por instituição (Portal da Transparência) e Transferegov, para as instituições federais (Butantan, institutos de Física e Química).
4. Estender às demais fundações estaduais, uma a uma, só depois de testar a resposta real de cada uma.


## FINEP (integrada em 25/11/2026)

- `https://download.finep.gov.br/Contratacao.xlsx` (7,8 MB, posição de 20/11/2026), várias abas; usamos `Projetos_Não_Reembolsavel_ICTs` (cabeçalho na linha que começa com "Demanda"): Demanda (edital), Ref, Contrato, Data Assinatura, Prazo Execução, Título,
  Proponente e Executor (com CNPJ, município, UF, região), UF Projeto, Valor Finep, contrapartidas, **Valor Pago**, Intervenientes, Status (ENCERRADO, EM PRESTACAO DE CONTAS, EM EXECUÇÃO, EM DESEMBOLSO, RESCINDIDO) e Resumo Publicável.
- Conferido: 9.114 contratos únicos, 2002–2026, R$ 25,61 bi contratados, R$ 21,06 bi liberados (82,3%), todos os estados (SP 1.783, RJ 1.615, RS 824, MG 754, PR 467...). 5 projetos com liberado acima do contratado. Sem nome de pesquisador.
- Outras abas (não usadas): crédito direto e descentralizado, subvenção direta e descentralizada (empresas), investimento direto (startups), ANCINE. `Liberacao.xlsx` (32 MB) tem os desembolsos por data: daria a curva de liberação de cada projeto.

## Resultado do diagnóstico pelo robô (25/11/2026, `scripts/diag_pesquisas.py`)

| Fonte | O que o robô achou |
|---|---|
| FINEP | Planilhas abertas em `download.finep.gov.br` (ver acima). O site novo (`www.finep.gov.br/transparencia`) dá 404; o legado abre. |
| CNPq | `dadosabertos.cnpq.br` e `gov.br/.../consulta-de-dados` resetam a conexão até pelo robô. `bi.cnpq.br` abre, mas é painel agregado (Tableau). |
| FAPERJ | Busca em `siteantigo.faperj.br/servicos/buscaprojetosinfaperj/busca_projeto.phtml`, formulário POST para `busca_resultados.phtml` (campos `edicao`, `nome_pesquisador`, `titulo_projeto`, `palavra_chave`, `area_conhecimento`, `pessoa_juridica`, `pagina`). Resposta de verdade ainda não testada. |
| FAPESP | `bv.fapesp.br/pt/` abre; `pt/pesquisador/` e `pt/dados-abertos/` estouraram 60 s; `dadosabertos.fapesp.br` não existe. Sem arquivo achado. |
| Transferegov | `dadosabertos.transferegov.sistema.gov.br` e `www.transferegov.sistema.gov.br` não resolvem DNS no robô; `api.transferegov.gestao.gov.br` dá 404 na raiz. |
| Portal da Transparência | Página de downloads abre, com "Favorecidos - PJ", "Convênios", "Recursos transferidos"; o HEAD de `despesas/202509` redirecionou para `dadosabertos-download.cgu.gov.br` e deu 403. |
| Fundações estaduais | Abriram: FAPERGS, FACEPE, FAPESB, FAPES (tem "Resultados de Projetos Apoiados pela Fapes"), Fundação Araucária, FAPEG, FAPEMA, FAPERN, FAPESPA, FAPEMAT, FUNDECT. Não abriram: FUNCAP e FAPESC (erro de certificado), FAPDF, FAPEAM, FAPEAL, FAPESQ, FAPITEC (tempo esgotado ou conexão recusada). Nenhuma mostrou arquivo de projetos na página inicial. |
| Butantan, Fiocruz, Embrapa, EMBRAPII | Butantan e Fiocruz abrem, sem arquivo de projetos com valor; Embrapa estourou o tempo; EMBRAPII lista projetos em páginas, sem planilha. OpenAlex responde (só identificação). |
