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

## Novidades da v0.5 (out/2026)
- Site sem números de exemplo quando há servidor ou cópia dos dados: hemiciclo em que cada bola é uma pessoa (passar o
  mouse mostra quem é), mapa dos partidos com cadeiras reais, Eleições com mapa do país, zoom no estado e resultado por
  região, Dívidas com um quadro por tipo (pública, estados, cidades, famílias, empresas) e aba de recuperação judicial,
  resumo de cada artigo da Constituição (`CF_RESUMO`), topo só com o botão lua/sol (sem login e configurações).
  Código no bloco "v0.5" do script do site.
- Eleições 2026 (1º turno) no robô; `tse-resultados` grava o total do Presidente em `uf=BR`; `/eleicoes/{ano}/estados`.
- `receita-recuperacao-judicial` (`app/collectors/cnpj_base.py`) e `/recuperacao-judicial`.

## Novidades da v0.6 (out/2026)
- Segurança pública: `app/collectors/seguranca.py` (Sisdepen semestral, Anuário FBSP T01, Sinesp VDE mensal desde 2015,
  Raio-X das forças/efetivo) e `GET /seguranca` (por estado, Brasil, últimos 12 meses, histórico por ano). Site: aba
  Segurança Pública (primeiro "por dia"), quadro no Início e seção na ficha do estado. Procurados (BNMP/CNJ) bloqueado
  fora do Brasil.
- Sem chave: `transparencia-orcamento` (arquivo anual do Portal, orçamento por órgão → aba Órgãos), `noticias-politica`
  (RSS; robô a cada 6 h), `bcb-scr-estados` (SCR.data: dívida e inadimplência por UF → mapa das famílias em Dívidas).
- Fotos e logos: `scripts/midia_site.py` gera `site/midia/` (fotos oficiais Câmara/Senado/TSE, retratos da Wikipédia de
  ministros e tribunais, logos de partidos e brasões das polícias da Wikimedia Commons). O site publicado não carrega
  imagens de fora: o bloco "fotos oficiais e logos" do script troca as iniciais e as cores pelas imagens de `midia/`.
- Eleições 2018 e 2020 no robô; Dívidas numa tela só (seletor + mapa + zoom); Obras com abas por situação e barra de
  etapas/prazo; hemiciclo com bolas que se mexem e ministros/tribunais com uma bola por pessoa.

## Novidades da v0.7 (out/2026)
- Segurança: um seletor único (mortes e crimes / prisões / polícia) comanda os números do país, o mapa, o ranking e o gráfico
  mensal; a ficha do estado não mostra dados do país e arredonda os valores. O Início tem só os quadros (sem mapa do país).
  Batalhões: `scripts/midia_site.py` acha as unidades na Wikipédia (`descobrir_unidades`) e grava em `logos.json` (`unidades`);
  o site junta com a lista fixa `UNIDADES`. Efetivo só quando a Wikipédia informa; data do último concurso não existe em base aberta.
- Eleições: candidatos clicáveis (`#/candidato/<sq>`, `P.candidato`, API `/eleicoes/candidato/{sq}`); governadores e senadores
  ganham a tabela de mais votados por estado. O snapshot guarda o perfil de presidente, governador e senador (`_candidato`) e não
  duplica mais a resposta sem `turno` (a ficha do estado pede `turno=1`).
- Órgãos: todos os anos desde 2014 e botões por tipo de órgão. Notícias: 5 assuntos, escolha do veículo com logo
  (`logos.json` → `veiculos`), mais veículos em `app/collectors/noticias.py` (feeds por tema, charset ISO-8859-1 e HTML escapado tratados).
- Desde 1985: `bcb-series` (SGS) desde 1985 com seletor de período em Indicadores; proposições PEC/PLP/MPV/PDL/PDC/PLN desde 1985
  (`HISTORICO` em `scripts/coleta_ci.py`). Eleições: o TSE só publica dados abertos a partir de 1994 (1989 e antes não existem em base aberta).
- Impostômetro: federal (Receita) + estaduais e municipais (`siconfi-tributos`, RREO Anexo 03 de cada estado e prefeitura, 12 meses); prefeituras sem relatório estimadas pela média por habitante da UF.
- Imagens: retratos até 360 px de altura (JPEG 78; Câmara usa a versão `jpgmaior`) e logos até 256 px (PNG); nunca amplia. 720p/1080p reais não cabem no limite de 256 MB do Artifact.

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

## IA do BRASIL+ (out/2026)
- Tela `#/ia` (bloco "IA do BRASIL+" do script do site; caixa no menu lateral e botão "Perguntar à IA" nos perfis).
  No site publicado como Artifact usa o Claude pela capacidade `sample` (declarar `capabilities: {downloads: true, sample: {}}`
  ao publicar), com ferramentas que leem os dados do site: ranking_gastos, mais_votados, tempo_no_poder, perfil_parlamentar,
  noticias, politicos_em_alta, resultado_eleicao, resumo_estado, buscar. Sem o Claude, o "modo simples" (`iaLocal`) responde
  gastos, mais votados, tempo no poder e notícias com as mesmas ferramentas.
- Índice `/ia/indice` (`app/ia_indice.py`): ranking da cota parlamentar, até 40 mais votados por eleição e cargo e mandatos
  por pessoa desde 1994. O robô grava junto da cópia (`exportar_snapshot.py`); para uma cópia pronta: `python -m scripts.indice_ia`.
  Limitações: TSE 2002 marca todos os candidatos como eleitos (2002 só conta para presidente); faltam presidente 2006/2010;
  a pessoa é reconhecida pelo nome no mesmo estado (homônimos não são unidos).

## Padrão visual (v0.9, out/2026)
- Paleta: azul #2F6FED (links, botões, seleção), azul-marinho #1D2939 (texto), fundo #F5F7FA, pastéis por região
  (`REGCOL`). Bloco CSS "v0.9" no fim do `<style>` do site.
- Mapas: cor sólida por estado, divisas brancas, 5 faixas com o mesmo número de estados (`faixasDe`, `corFaixa`,
  `legFaixas` com os limites escritos). Nada de degradê entre estados. Eleições (presidente): modos "Quem venceu",
  "% de um candidato" e "Diferença entre os 2 primeiros" (escala divergente com empate em cinza).
- Gráficos: os 3 maiores em cor viva e os 3 menores em pastel (`rankPos`, `rankCor`).
- Tabelas: um padrão só (`table()`): 10 primeiras linhas + "Ver todos", ordenação ao tocar no título da coluna,
  cabeçalho fixo nas listas longas, números à direita.
- Formatos (v1.0): número em destaque = `.kpis/.kpi` ou pares `.facts` (blocos iguais, mesma letra em todo o site);
  comparação = barras (`hbars`, efetivo, eleições) com cores de `rankCor`; lista de registros = `table()`. CSS no bloco "v1.0".
- Maiores × menores: `rankDuplo(vals,fmt,{alto,baixo,corAlto,corBaixo})` — dois gráficos (5 maiores e 5 menores, 3 primeiros
  fortes e 2 apagados). Violência e dívidas: mapa vermelho (`SCALE_VERM`), maiores em vermelho e menores em verde.
- Projetos: situação via `camara-proposicoes-situacao` (arquivo anual da Câmara `proposicoes-AAAA.json`, campo
  `ultimoStatus`); no site `sitProj`/`sitProjTag` traduzem para palavras simples ("Aguardando votação", "Virou lei"…).
- Gráficos em linha (maiores × menores): `linhasDuplo(serie,anos,vals,fmt,…)` — 5 linhas por gráfico, 3 primeiras vivas e
  grossas, 2 apagadas; sem 2 anos de dados cai para `rankDuplo` (barras). Segurança usa `segHist` (histórico anual do
  `/seguranca`); dívida e arrecadação usam `/historico-estados` (anos coletados pelo robô: receita, tesouro e siconfi-divida).
