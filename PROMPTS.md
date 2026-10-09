# BRASIL+ — Prompts do projeto (fase de APIs)

Cole um prompt por conversa, junto com os arquivos relevantes do projeto.
✅ = já feito neste pacote · ⏳ = próximo passo

---

## ✅ 1. Estrutura do backend
> Crie o backend do BRASIL+ em Python com FastAPI + PostgreSQL (SQLAlchemy 2), com: tabelas para parlamentares, proposições, votações, votos e despesas; uma tabela genérica de staging (fonte, tipo, chave, uf, ano, valor, JSON) para as demais fontes; log de coletas; cliente HTTP com retentativa; CLI de coleta e docker-compose do Postgres.

## ✅ 2. Câmara dos Deputados
> Implemente o coletor da API de Dados Abertos da Câmara (v2): deputados, proposições por período, votações com voto nominal de cada deputado, cota parlamentar (CEAP) por ano e órgãos. Paginação pelos links rel=next, janelas mensais e upsert idempotente.

## ✅ 3. Senado Federal
> Implemente o coletor da API de Dados Abertos do Senado: senadores em exercício, votações nominais do plenário por período (com voto de cada senador) e matérias por ano. A API mistura lista e objeto único — trate de forma defensiva.

## ✅ 4. Indicadores (IBGE)
> Colete da API de agregados do IBGE (SIDRA) os indicadores por estado: população estimada, PIB e PIB per capita, últimos 3 períodos, guardando unidade e período. Deixe fácil adicionar novos indicadores.

## ✅ 5. Arrecadação dos estados (SICONFI)
> Colete do SICONFI o RREO Anexo 01 (balanço orçamentário) e Anexo 03 (receita corrente líquida) de cada estado, por ano e bimestre.

## ✅ 6. Dívidas (SICONFI)
> Colete do SICONFI o RGF Anexo 02 (dívida consolidada) do Executivo de cada estado, por ano e quadrimestre.

## ✅ 7. Contratos (PNCP)
> Colete os contratos do Portal Nacional de Contratações Públicas por período (janelas mensais), com órgão, UF, fornecedor, objeto e valor global.

## ✅ 8. Portal da Transparência (órgãos, contratos e gastos)
> Integre a API do Portal da Transparência (com chave no .env, respeitando o limite de requisições): órgãos SIAFI, contratos por órgão e período, e despesas por órgão superior.

## ✅ 9. Obras (ObrasGov)
> Colete os projetos de investimento (obras federais) do ObrasGov.br por UF, com situação e valor previsto.

## ✅ 10. Candidatos (TSE)
> Importe os candidatos do TSE a partir do CSV zipado de cada eleição (latin-1, separador ;), com filtro por UF e gravação em lotes.

## ✅ 11. API REST para o site
> Crie os endpoints que alimentam os popouts: lista/detalhe de parlamentares (com últimos votos e gastos), lista/detalhe de votações (placar geral, por partido e por UF), proposições, despesas, registros genéricos com filtros, resumo por estado e disparo/log de coletas protegido por token.

---

## ✅ 12. Arrecadado × redistribuído × retornado por estado
> No BRASIL+ (FastAPI + Postgres, arquivos anexos), quero preencher o bloco `fluxo_federativo` do endpoint `/estados/{uf}/resumo`. Pesquise e integre: (a) a arrecadação federal por UF da Receita Federal (dados abertos de arrecadação por estado); (b) as transferências constitucionais da União aos estados e municípios por UF (FPE, FPM, IPI-Exportação, Fundeb, Lei Kandir etc., do Tesouro Transparente); (c) os gastos diretos da União em cada UF, se houver fonte confiável. Calcule por estado e ano: quanto foi arrecadado, quanto a União redistribuiu ao país e quanto retornou àquele estado, deixando claro na resposta da API a metodologia e as limitações (ex.: arrecadação registrada na sede da empresa).

## ✅ 13. Legislação
> Adicione ao BRASIL+ o módulo de legislação: coletor de normas federais (LexML e/ou endpoint de legislação do Senado), com tipo, número, data, ementa e link do texto, e ligação com a proposição que deu origem quando possível. Inclua endpoint `/legislacao` com busca por texto e filtros.

## ✅ 14. Resultados das eleições
> Adicione ao coletor do TSE os resultados de votação por candidato e por município (arquivos votacao_candidato_munzona), ligados aos candidatos já importados. Crie `/eleicoes/{ano}/{uf}` com eleitos, votos por partido e comparativo com a eleição anterior.

## ✅ 15. Normalizar o staging
> No BRASIL+, transforme os dados da tabela `registros` em tabelas próprias para contratos, obras, candidatos, indicadores e finanças estaduais, com Alembic para migrações, índices para as buscas do site e full-text search em português no Postgres.

## ✅ 16. Ligações entre dados
> Crie ligações cruzadas no BRASIL+: fornecedores (CNPJ) que aparecem em contratos e na cota parlamentar, parlamentar ↔ candidato do TSE (por nome/CPF), proposição ↔ votações. Exponha isso nos popouts (ex.: "este fornecedor também recebeu de...").

## ✅ 17. Agendamento e deploy (scripts/agendar.py, docker-compose.prod.yml, DEPLOY.md)
> Configure o BRASIL+ para rodar sozinho: agendamento das coletas (diário para Câmara/Senado/PNCP, mensal para IBGE/SICONFI/obras), deploy da API e do Postgres em uma hospedagem barata, backups e monitoramento de falhas usando a tabela `coletas`.

## ✅ 18. Integrar o site (site/index.html servido em /)
> Conecte o frontend do BRASIL+ (visual branco com pouco azul, seleções abrindo em popout) aos endpoints da API: popout de pessoa, de votação, de contrato e de estado, com estados de carregamento e erro.

## 🟡 19. Validar com dados reais (validados: Câmara, Senado, legislação, PNCP, ObrasGov, SICONFI, IBGE, Tesouro; faltam Receita, TSE e Portal da Transparência — arquivos/chave, validar ao rodar no computador)
> Rodei os coletores do BRASIL+ contra as APIs reais e este é o resultado de `GET /coletas` e exemplos das respostas brutas [colar aqui]. Corrija os nomes de campos, paginação e parâmetros que não bateram, e adicione testes com essas respostas reais.
