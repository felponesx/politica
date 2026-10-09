# BRASIL+ — contexto para o Claude Code

## O que é
BRASIL+ ("Transparência em um só lugar"): plataforma independente de dados públicos brasileiros.
Este repositório é o **backend** (Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL).
O site (frontend) é separado: visual predominantemente branco com pouco azul, e toda seleção
(estado, pessoa, contrato, votação, lei) abre em janela flutuante (popout) consumindo esta API.

O dono do projeto é o Felipe. Fale com ele em português do Brasil, de forma simples e direta.

## Estado atual (out/2026)
Feito e testado (`pytest -q` passa em SQLite e em Postgres 16):
- Coletores: Câmara, Senado (serviço novo `/dadosabertos/votacao`), IBGE, SICONFI, PNCP, Portal da Transparência
  (precisa de chave), ObrasGov, TSE (candidatos e resultados), Receita (arrecadação por UF), Tesouro (transferências),
  legislação (base de normas do Senado).
- Staging em `registros` → tabelas normalizadas (`app/normalizar.py`), ligações entre bases (`app/ligacoes.py`).
- Busca em português com unaccent + full-text + trigramas (migração 0002, só Postgres).
- Fluxo federativo por estado: arrecadado × redistribuído × retornado (`app/fluxo.py`).
- Lista completa de tarefas: `python -m scripts.coletar --help`. Log de cada coleta: tabela `coletas` / `GET /coletas`.

Validação contra as fontes reais (09/10/2026, robô do GitHub Actions — ver README, "Validação com dados reais"):
todas as fontes da carga inicial, TSE 2022/2024 e Banco Central funcionam; corrigidos com as respostas reais: cota da
Câmara (arquivo anual, `ideCadastro`), votos 404 de votação simbólica, Receita (Accept */*), CAPAG (cabeçalho),
SGS (página HTML de erro), CNPJ (reserva). Bloqueados fora do Brasil/para robôs: LexML e ALMG.
Não rodados: Portal da Transparência (chave), PGFN, Defesa Civil.

## Robô de coleta e site sem servidor (out/2026)
- `.github/workflows/coletar-dados.yml` + `scripts/coleta_ci.py`: coleta no GitHub Actions (Postgres de serviço, banco
  guardado no cache do Actions entre execuções), resumo em `/coletas` e cópia estática da API em `site/dados/`
  (`scripts/exportar_snapshot.py`). Rodar só algumas tarefas: Actions > Run workflow > campo "tarefas".
- `.github/workflows/diagnostico.yml` + `scripts/diagnostico_ci.py`: respostas brutas das fontes, para conferir antes
  de corrigir um coletor (o ambiente do Claude Code na nuvem pode não ter acesso às fontes).
- O site (`site/index.html`), sem servidor, lê `dados/manifest.json` e `dados/s<N>.json` (bloco "cópia estática").
  Coletas com parte das fontes falhando ficam com status `parcial` (`Contador.avisos`).

## Novidades da v0.2 (out/2026)
- O site completo está em `site/index.html`, servido em `/`. A ligação com a API fica no bloco
  "dados reais: servidor BRASIL+" do script (cada tela P.<nome> usa a API e volta para a demonstração sem dados).
- Fontes novas (ainda NÃO validadas contra as reais): IBGE municípios e indicadores sociais, SICONFI Anexo 02
  (despesa por função), Transparência gastos de todos os órgãos, PGFN dívida ativa, CAPAG, BrasilAPI (CNPJ/sócios),
  planilhas de desastres. Endpoints em `app/routers/v02.py`. Migração 0004.
- Agendador: `scripts/agendar.py` (APScheduler, trava, alertas em `app/alertas.py`).
- Produção: `docker-compose.prod.yml` + `DEPLOY.md` (Caddy HTTPS, API com usuário só leitura, backup diário).
- Proteções: `app/seguranca.py` (limite por IP, cabeçalhos, CSP no site). POST /coletas exige token de 24+ caracteres.

## Novidades da v0.3
- Coletores: `bcb.py` (SGS), `agenda.py` (eventos do dia), `congresso_extra.py` (tramitações, atuação, CEAPS),
  `tse_financas.py` (bens e contas de campanha), `lexml.py` (leis estaduais). Endpoints em `app/routers/v03.py`.
- Migrações 0005 (normas estaduais) e 0006 (candidato_financas).
- Site: aba Constituição e Leis; contadores, economia, agenda ao vivo, tramitação, atuação, comparação e exportação
  ligados à API (blocos "v0.3" no script do site).

## Missão nesta sessão (em ordem)
1. **Subir o ambiente:** Postgres via `docker compose up -d` (se não houver Docker, usar SQLite no `.env`
   e avisar que a busca avançada fica limitada). Criar `.venv`, instalar `requirements.txt`, copiar `.env.example`.
2. **Rodar cada coletor contra a API real**, com períodos curtos primeiro (ex.: 1 mês, 1 UF). Para cada fonte:
   conferir `GET /coletas` e amostras no banco. Se um campo vier vazio ou errado, inspecionar a resposta bruta,
   corrigir o coletor e **adicionar a resposta real (resumida) como fixture em `tests/test_formatos_reais.py`**.
   Prioridade: Receita e Tesouro `por_estado_municipio` (alimentam o fluxo federativo), depois TSE (comece com
   `uf=SP`), depois o resto.
3. **Subir a API** (`uvicorn app.main:app --reload`) e conferir os popouts principais em `/docs`:
   `/parlamentares/{id}`, `/parlamentares/{id}/ligacoes`, `/votacoes/{id}`, `/estados/{uf}/resumo`,
   `/estados/{uf}/fluxo`, `/fluxo-federativo`, `/legislacao/{id}`, `/proposicoes/{id}`, `/contratos/{id}`,
   `/fornecedores/{cnpj}`, `/eleicoes/{ano}/{uf}`, `/busca`.
4. Rodar as fontes da v0.2 (ibge-municipios, ibge-indicadores-sociais, siconfi-despesas-funcao, tesouro-capag,
   cnpj-fornecedores, transparencia-gastos-todos, pgfn-divida-ativa) e validar como no passo 2.
5. Deploy: seguir `DEPLOY.md`.

## Regras do projeto
- Mudou `app/models.py`? Gere migração: `alembic revision --autogenerate -m "..."` e revise o arquivo
  (o autogenerate não conhece os índices de busca da 0002 — nunca deixe ele apagá-los; dê nome às FKs).
- Coletores devem ser idempotentes (upsert) e registrar execução via `registrar_coleta`.
- APIs do governo mudam: leitura defensiva (`pegar`, `achar_lista`, `como_lista` em `app/utils.py`).
- Respeitar limites das fontes (Portal da Transparência ~90 req/min; Senado máx. 60 dias por consulta).
- Cruzamentos (fornecedores, candidaturas) sempre com o `AVISO` de que aparecer em duas bases não indica
  irregularidade. Em caso de homônimo, não ligar.
- Votação secreta no Senado: usar o placar oficial, nunca inferir voto individual.
- Fluxo federativo: sempre devolver a metodologia e as limitações junto dos números.
- Nunca commitar `.env` nem chaves.
