# BRASIL+ — Backend de dados (v0.3)

> Vai usar o Claude Code? O arquivo `CLAUDE.md` tem todo o contexto e o passo a passo.

FastAPI + PostgreSQL. Coletores das fontes oficiais gravam no banco; a API REST serve o site (popouts de pessoa, votação, estado, contrato...).

## Rodar em 5 passos
```bash
docker compose up -d                  # sobe o Postgres
cp .env.example .env                  # (opcional) coloque a chave do Portal da Transparência
pip install -r requirements.txt
python -m scripts.coletar inicial     # carga dos últimos 90 dias (fontes sem chave)
uvicorn app.main:app --reload         # site em http://localhost:8000  ·  API em http://localhost:8000/docs
```

## O site já vem ligado à API
O frontend completo está em `site/index.html` e é servido pelo próprio backend em `http://localhost:8000`.
Aberto assim, ele se conecta sozinho (selo **Dados oficiais** no topo) e estas telas passam a usar os dados coletados:

| Tela do site | Endpoints usados |
|---|---|
| Agora | `/votacoes`, `/proposicoes`, `/legislacao`, `/contratos?ordenar=data` |
| Votação (popout) | `/votacoes/{id}` — placar, voto por partido, mapa do “Sim” por estado, lista nominal |
| Candidatos e Indicações | `/parlamentares` (Câmara/Senado) e `/candidatos` (TSE); popout `/parlamentares/{id}`, `/despesas`, `/ligacoes` |
| Projetos e proposições | `/proposicoes`, `/proposicoes/{id}` |
| Legislação e normas | `/legislacao`, `/legislacao-resumo`, `/legislacao/{id}` |
| Empresas e Contratos | `/contratos`, `/contratos/{id}`, `/fornecedores/{cnpj}`, `/fornecedores-cruzados` |
| Obras | `/obras`, `/obras/{id}` |
| Estado (página e zoom do mapa) | `/estados/{uf}/resumo`, `/parlamentares?uf=`, `/obras-resumo/{uf}` |
| Arrecadação | `/fluxo-federativo` |
| Eleições | `/eleicoes/anos`, `/eleicoes/{ano}/{uf}/cargos`, `/eleicoes/{ano}/{uf}` |
| Busca (Ctrl + K) | `/busca` |
| Fontes e metodologia | `/coletas` + campo para apontar outro servidor |

Se uma fonte ainda não foi coletada, a tela avisa qual coleta rodar e mostra a demonstração no lugar.
Telas sem fonte no backend (gastos por função, dívidas de pessoas e empresas, riscos por cidade, indicadores sociais,
órgãos, quadro societário) continuam em modo demonstração. Para hospedar o site em outro domínio, informe o endereço
da API em **Fontes > Servidor de dados** (o CORS já está liberado para leitura).
Ao atualizar o site, substitua `site/index.html`.
Sem Docker? Use `DATABASE_URL=sqlite:///./brasilplus.db` no `.env`.

## Fontes já integradas
| Módulo do site | Fonte | Tarefa |
|---|---|---|
| Deputados, votações, votos, proposições, cota parlamentar, órgãos | Câmara (Dados Abertos) | `camara-*` |
| Senadores, votações nominais, matérias | Senado (Dados Abertos) | `senado-*` |
| Indicadores por estado (população, PIB, PIB per capita) | IBGE agregados | `ibge-indicadores` |
| Arrecadação/receitas e RCL dos estados | SICONFI (RREO) | `siconfi-receitas` |
| Dívida dos estados | SICONFI (RGF) | `siconfi-divida` |
| Contratos (todas as esferas) | PNCP | `pncp-contratos` |
| Órgãos, contratos e gastos federais | Portal da Transparência (chave) | `transparencia-*` |
| Obras federais | ObrasGov.br | `obrasgov-obras` |
| Candidatos | TSE (CSV) | `tse-candidatos` |
| Resultados das eleições (por candidato, partido e município) | TSE (CSV) | `tse-resultados` |
| Arrecadação federal por estado | Receita Federal (CSV) | `receita-arrecadacao` |
| Transferências da União a estados e municípios | Tesouro Nacional (API) | `tesouro-transferencias` |
| Legislação federal (leis, LCs, emendas, MPs, decretos) | Senado (base de normas) | `legislacao-normas` |
| Situação e norma gerada de cada projeto | Câmara (detalhe da proposição) | `camara-proposicoes-detalhe` |
| Municípios (5.570), população e PIB municipal | IBGE localidades + SIDRA | `ibge-municipios` |
| Indicadores sociais por município | IBGE SIDRA (lista editável) ou planilha (IDHM, DataSUS, INEP) | `ibge-indicadores-sociais`, `indicador-arquivo` |
| Gastos por função (União, estados, capitais) | SICONFI RREO Anexo 02 | `siconfi-despesas-funcao` |
| Gastos de todos os órgãos federais | Portal da Transparência (chave) | `transparencia-gastos-todos` |
| Dívida ativa da União por estado e maiores empresas devedoras | PGFN (dados abertos trimestrais) | `pgfn-divida-ativa` |
| Capacidade de pagamento dos municípios | Tesouro (CAPAG) | `tesouro-capag` |
| Cadastro e quadro societário das empresas | Receita Federal via BrasilAPI | `cnpj-fornecedores` (+ sob demanda) |
| Desastres reconhecidos por município | Defesa Civil (planilha S2ID/Atlas) | `desastres` |
| Leis estaduais (leis, LCs, emendas às constituições estaduais) | Portal LexML (SRU) | `lexml-estaduais` |
| Economia e dívida do país (Selic, IPCA, desemprego, dólar, dívida bruta/líquida, juros, endividamento e inadimplência) | Banco Central (SGS) | `bcb-series` |
| Sessões e reuniões de hoje (ao vivo) | Câmara (eventos e pauta) e Senado (agenda) | `congresso-agenda` (a cada 15 min) |
| Tramitação e autores dos projetos | Câmara | `camara-tramitacoes` |
| Comissões e discursos dos parlamentares | Câmara e Senado | `congresso-atuacao` |
| Cota dos senadores (CEAPS) | Senado | `senado-ceaps` |
| Patrimônio declarado e contas de campanha | TSE | `tse-bens`, `tse-contas` (por estado) |
| Gastos por função de qualquer prefeitura | SICONFI | `siconfi-despesas-funcao esferas=M` |
| Contorno dos municípios (mapa de eleição por cidade) | IBGE (malhas) | `ibge-malhas` |
| Deputados estaduais em exercício e votações das Assembleias | ALMG (API JSON) e Alesp (XML); demais por planilha | `assembleias`, `assembleia-arquivo uf=XX arquivo=...` |

Liste tudo com `python -m scripts.coletar --help`. Cada execução fica registrada em `GET /coletas`.

## Endpoints principais
- `GET /parlamentares` · `GET /parlamentares/{id}` (popout: perfil + últimos votos + gastos)
- `GET /votacoes` · `GET /votacoes/{id}` (placar geral, por partido e por UF)
- `GET /proposicoes` · `GET /parlamentares/{id}/despesas`
- `GET /registros?fonte=pncp&tipo=contrato&uf=SP` (contratos, obras, candidatos, indicadores, finanças)
- `GET /estados/{uf}/resumo` (popout de estado)
- `GET /estados/{uf}/fluxo?ano=2025` (arrecadado × redistribuído × retornado, com metodologia)
- `GET /fluxo-federativo?ano=2025` (ranking dos 27 estados para mapa/tabela)
- `GET /legislacao?q=&tipo=LEI&ano=` · `GET /legislacao/{id}` (popout: norma + projeto de origem + votações)
- `GET /legislacao-resumo` (normas por ano e tipo)
- `GET /eleicoes/anos` · `GET /eleicoes/{ano}/{uf}/cargos`
- `GET /eleicoes/{ano}/{uf}?cargo=governador&turno=1` (eleitos, mais votados, votos por partido, comparação com 4 anos antes; `unidade=` para município)
- `GET /eleicoes/{ano}/{uf}/mapa?cargo=governador` (vencedor por município) · `GET /eleicoes/candidato/{sq}`
- `GET /busca?q=educacao` (busca única: parlamentares, candidatos, proposições, leis, votações, contratos, obras)
- `GET /contratos?uf=BA&esfera=M&ordenar=valor` · `GET /contratos/{id}` (popout + outros contratos do fornecedor)
- `GET /obras?uf=SP&tipo=rodovia` · `GET /obras/{id}` · `GET /obras-resumo/{uf}`
- `GET /candidatos?ano=2024&uf=SP&cargo=PREFEITO` · `GET /indicadores?nome=populacao`
- `GET /fornecedores/{cnpj}` (popout: contratos públicos + cota parlamentar do mesmo CNPJ)
- `GET /fornecedores-cruzados` (empresas que aparecem nas duas bases)
- `GET /proposicoes/{id}` (popout: projeto + votações + lei gerada) · `GET /parlamentares/{id}/ligacoes` (candidaturas no TSE + fornecedores com contratos públicos)
- `GET /municipios?uf=&q=&capag=` · `GET /municipios/{codigo_ibge}` (popout de cidade)
- `GET /indicadores-sociais/nomes` · `GET /indicadores-sociais?nome=&uf=`
- `GET /gastos/funcao?esfera=U|E|C&uf=&ano=` · `GET /gastos/evolucao` · `GET /gastos/entes`
- `GET /orgaos?q=&ano=` · `GET /orgaos/{codigo}`
- `GET /dividas/estados` · `GET /dividas/devedores?uf=&q=` · `GET /dividas/municipios?uf=` (CAPAG)
- `GET /empresas/{cnpj}` (cadastro, sócios, dívida ativa, contratos e cota)
- `GET /legislacao?esfera=estadual&uf=SP` · `GET /legislacao-estados` (normas estaduais por UF)
- `GET /economia?nomes=` · `GET /contadores` (impostômetro e gastômetro com base oficial)
- `GET /agora/eventos?dia=` · `GET /parlamentares/{id}/atuacao`
- `GET /mapa/estados` (métricas do mapa inicial) · `GET /malhas/{uf}` · `GET /empresas-setores` · `GET /empresas?setor=&uf=&q=`
- `GET /assembleias` (estados com dados da própria Assembleia) · `GET /parlamentares?casa=al-mg` · `GET /votacoes?casa=al-sp`
- `GET /exportar` · `GET /exportar/{conjunto}.csv?uf=&ano=` (CSV para Excel)
- `GET /riscos?uf=&anos=10` · `GET /partidos/composicao` (Câmara, Senado, Assembleias, governadores, prefeitos)
- `POST /coletas/{tarefa}` com header `x-admin-token` (24+ caracteres; desligado em produção)

## Agendamento e produção
- `python -m scripts.agendar` deixa as coletas rodando sozinhas (diário, semanal, mensal e trimestral);
  `--listar` mostra a agenda. Falhou 3 vezes seguidas → alerta no Telegram/webhook configurado no `.env`.
- Deploy com HTTPS, usuário de banco só leitura e backup diário: veja **DEPLOY.md**.

## Fontes da v0.2 e v0.3: o que conferir na primeira coleta
Assembleias: a ALMG e a Alesp não publicam um formato de votos estável; os adaptadores procuram os campos pelo nome
(`app/collectors/assembleias.py`). Para outro estado, importe a planilha de deputados da casa ou crie um adaptador seguindo o de MG.
v0.3 (também não rodadas contra as fontes reais): Banco Central (códigos em `SERIES`, `app/collectors/bcb.py`),
agenda da Câmara e do Senado, tramitações, atuação, CEAPS do Senado (endereços em `app/config.py`) e arquivos de bens e
contas do TSE.

Escritas a partir da documentação pública, testadas com respostas simuladas e no Postgres 16, mas **ainda não rodadas contra as
fontes reais**: IBGE municípios/indicadores sociais (as tabelas do SIDRA ficam em `INDICADORES_SOCIAIS`, em
`app/collectors/municipios.py`), SICONFI Anexo 02, PGFN (o endereço dos arquivos segue o padrão
`dadosabertos.pgfn.gov.br/AAAA_trimestre_TT/`), CAPAG (CKAN do Tesouro), BrasilAPI e planilhas da Defesa Civil e LexML (as expressões de busca ficam em `lexml_cql_estadual`, em `app/config.py`; a coleta
tenta uma por uma e usa a primeira que trouxer resultado).
Se algo não bater, o erro aparece em `GET /coletas`; use o prompt 19 do `PROMPTS.md`.
Privacidade: pessoas físicas da dívida ativa só entram nos totais por estado; CPF de sócios vem mascarado da fonte.

## Validação com dados reais
Validados com respostas reais (07/10/2026): votações da Câmara, senadores e votações do Senado (serviço novo
`/votacao`), legislação, contratos do PNCP, obras do ObrasGov, dívida dos estados (SICONFI), indicadores do IBGE e
transferências do Tesouro (`tests/test_formatos_reais.py`). Ainda não validados: Receita, TSE e Portal da Transparência
(são arquivos grandes ou exigem chave — confira em `GET /coletas` na primeira execução).

## Importante
O código foi testado com respostas simuladas (`pytest -q`), mas **não contra as APIs reais** (o ambiente onde foi gerado não tinha acesso a esses sites). Na primeira execução, confira `GET /coletas`: se alguma fonte der erro ou vier com campos vazios, é ajuste de nome de campo — use o prompt 19 do `PROMPTS.md`.

### Eleições: carga recomendada
Os arquivos do TSE são grandes. Comece por um estado e duas eleições para ter o comparativo:
```bash
python -m scripts.coletar tse-resultados ano=2022 uf=SP
python -m scripts.coletar tse-resultados ano=2018 uf=SP
```

## Banco de dados e migrações
- A estrutura do banco é versionada com **Alembic** (`migrations/`). A API e a CLI aplicam as migrações pendentes
  sozinhas ao iniciar — não é preciso apagar o banco quando o projeto for atualizado.
- Ao mudar `app/models.py`, gere uma migração: `alembic revision --autogenerate -m "o que mudou"`.
- Se você criou um banco com uma versão anterior deste pacote (sem a tabela `alembic_version`), apague-o uma vez:
  `docker compose down -v && docker compose up -d`.
- Fluxo dos dados: coletor → `registros` (JSON bruto, staging) → tabelas normalizadas (`contratos`, `obras`,
  `candidatos`, `indicadores`, `financas_estaduais`). A normalização roda sozinha após cada coleta e é incremental;
  para refazer: `python -m scripts.coletar normalizar`.
- Busca em português (só no Postgres): ignora acentos ("educacao" acha "Educação") e entende variações das palavras
  ("escola" acha "escolas"). No SQLite a busca é simples.
- Testes: `pytest -q` (SQLite). Para testar com Postgres: `DATABASE_URL=postgresql+psycopg://... pytest -q`.

## Ligações entre bases
Rodam sozinhas após as coletas relevantes (ou `python -m scripts.coletar ligar`):
- **Votação → projeto:** pela matéria ("PLP 74/2026").
- **Parlamentar → candidatura no TSE:** nome de urna + UF + cargo. Se houver dois candidatos com o mesmo nome no
  mesmo ano, não liga (prefere ficar sem ligação a ligar errado).
- **Fornecedores:** o mesmo CNPJ em contratos públicos e na cota parlamentar. Toda resposta que mostra esse cruzamento
  traz um aviso de que aparecer nas duas bases não indica irregularidade — mantenha esse aviso visível no site.
