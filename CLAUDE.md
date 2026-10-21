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

## Notícias rápidas (out/2026)
- `.github/workflows/noticias.yml` + `scripts/noticias_rapido.py`: a cada 15 min lê os feeds (`buscar_feeds` em `app/collectors/noticias.py`),
  sem banco, e grava `site/dados/noticias.json` (formato de `GET /noticias`; só faz commit quando chega matéria nova; 10 dias, até 1.200).
  O site usa esse arquivo no lugar da cópia completa (`snapNoticias` em `snapLer`). Cada matéria ganha `casos`: escândalos citados no
  título/resumo (`app/escandalos.py` → `casos_da_materia`, palavra inteira; o caso de nome mais longo vence); a aba Notícias mostra a
  etiqueta do caso (leva a `#/escandalo/<slug>`) e a página do caso lista essas matérias na hora.
- O robô pesado (`coletar-dados.yml`) não tem mais agendamento: só roda pelo botão ou ao mudar o próprio arquivo. `exportar_snapshot.py`
  preserva `noticias.json` ao refazer a pasta (`ARQUIVOS_DE_OUTROS_ROBOS`). Atenção: o GitHub só dispara `schedule` pelo branch padrão.

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
- Padronização dos dados (`app/limpeza.py`): espaços sobrando, `&amp;` e acentos quebrados ("AquisiÃ§Ã£o") são corrigidos e as
  grafias da mesma sigla unificadas (PC do B/PCDOB → PCdoB, SD → SOLIDARIEDADE, PATRI → PATRIOTA; nomes antigos como PMDB e PFL
  ficam). Aplicada no `upsert` e na exportação da cópia; para uma cópia antiga: `python -m scripts.limpar_copia`.
  Valores negativos da fonte são reais (devolução do auxílio-moradia no CEAPS, dívida líquida negativa, IPCA com deflação).
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
- Sem tela própria nem item no menu: a caixa "IA do Brasil+" do menu lateral abre a janela da IA ao lado (`iaAbrir`, `#iaDock`;
  no celular, tela cheia) e a barra de pesquisa responde dentro dela (`iaNaBusca`, `#sIAbox`); botão "Perguntar à IA" nos perfis
  (`data-ia-abrir`). Links antigos `#/ia/<pergunta>` abrem a janela. Código no bloco "IA do BRASIL+" do script do site.
  No site publicado como Artifact usa o Claude pela capacidade `sample` (declarar `capabilities: {downloads: true, sample: {}}`
  ao publicar), com ferramentas que leem os dados do site: ranking_gastos, mais_votados, tempo_no_poder, perfil_parlamentar,
  noticias, politicos_em_alta, resultado_eleicao, resumo_estado, buscar. Sem o Claude, o "modo simples" (`iaLocal`) responde
  gastos, mais votados, tempo no poder e notícias com as mesmas ferramentas.
- Pesquisa na internet: `POST /ia/web` (`app/ia_web.py`) chama o Perplexity (Agent API, preset `low`) com a chave
  `PERPLEXITY_API_KEY` só no servidor (sem chave: 503). Limite diário (`perplexity_limite_dia`), pergunta até 600 caracteres
  e mesma pergunta guardada 1 h. No site, a ferramenta `pesquisar_web` e o último recurso do modo simples só existem com o
  servidor BRASIL+ no ar (`iaWebOn`; nunca no Artifact/cópia estática). Respostas sempre com fontes e o aviso de que não são
  dados oficiais.
- Busca na internet crua: `POST /busca/web` (`app/busca_web.py`, Perplexity Search API `POST https://api.perplexity.ai/search`):
  até 5 consultas por chamada (cobrada como 1), `max_results` 1–20, país BR, filtros de domínio (só permitidos ou só bloqueados
  com "-"), recência e datas; achata e tira links repetidos; respeita `Retry-After` no 429; limite `perplexity_busca_limite_dia`
  e cache de 1 h. A IA com o Claude usa a ferramenta `buscar_na_web`; no terminal: `python -m scripts.busca_web "consulta"`.
  `search_context_size` não existe nessa rota (o tamanho dos trechos é `max_tokens`/`max_tokens_per_page`).
- Índice `/ia/indice` (`app/ia_indice.py`): ranking da cota parlamentar, até 40 mais votados por eleição e cargo e mandatos
  por pessoa desde 1994. O robô grava junto da cópia (`exportar_snapshot.py`); para uma cópia pronta: `python -m scripts.indice_ia`.
  Limitações: TSE 2002 marca todos os candidatos como eleitos (2002 só conta para presidente); faltam presidente 2006/2010;
  a pessoa é reconhecida pelo nome no mesmo estado (homônimos não são unidos).

## Escândalos (out/2026)
- Aba "Escândalos" (acima de Notícias; `P.escandalos`, `P.escandalo`): 12 casos curados em `app/dados/escandalos/<slug>.json`
  (Collor/PC Farias, Anões do Orçamento, Mensalão, Mensalão mineiro, Sanguessugas, Lava Jato, Zelotes, Covaxin, emendas/orçamento
  secreto, joias sauditas, fraude no INSS, Banco Master). API `/escandalos` e `/escandalos/{slug}` (`app/escandalos.py`).
- Regras: toda pessoa, valor e marco tem link de fonte (sem fonte é descartado ao carregar); situação jurídica só com os termos de
  `SITUACOES` e a data da fonte; aviso de presunção de inocência em todas as telas; "Valor citado" sempre com a frase da fonte;
  prisão por outro processo só aparece marcada "(outro processo)" (`liberdade_outro_processo`); situação de prisão em `liberdade` + `liberdade_data`/`liberdade_fonte`/`liberdade_detalhe` (preso, prisão domiciliar, foragido, em liberdade, morreu), etiqueta na árvore e na tabela (`escPrisao`); só entra quem tem investigação formal e situação conhecida e recente.
- Árvore do esquema (`escArvore`/`escLinhas`): papéis segundo a acusação em `app/dados/escandalos/papeis/<slug>.json` (nível 1 apontados
  como chefes, 2 operadores, 3 executores/beneficiários; `acima` só quando a fonte diz a quem respondia; citação + fonte). Nível 1 só
  com "líder/chefe/comandante" na fonte. Absolvidos, anulados e arquivados saem dos andares e vão para a faixa "A acusação apontou,
  mas a Justiça não confirmou". Borda pela situação na Justiça.
- Atualizar: editar o JSON do caso e rodar `python -m scripts.escandalos_copia` (o robô já exporta pelas FIXAS).

## Padrão visual (v0.9, out/2026)
- Paleta: azul #2F6FED (links, botões, seleção), azul-marinho #1D2939 (texto), fundo #F5F7FA, pastéis por região
  (`REGCOL`). Bloco CSS "v0.9" no fim do `<style>` do site.
- Cores (v1.1): pastéis de gráficos, barras e regiões mais vivos (claridade −8%, saturação +15%); fundos bem claros ficam. Impostômetro
  e gastômetro com a paleta viva (#2F6FED, #1BAF7A, #F5A524, #EB6834, #8B5CF6). Em volta do país, sombra suave em vez de
  traço (`svg.geo` com `drop-shadow`, variáveis `--sombra1`/`--sombra2`): escura no claro, brilho claro no escuro.
- Zoom no estado ("efeito Spiderman", `flyState`/`inlineZoomIn`/`inlineZoomOut`): no celular (`zLeve`) só o estado voa, sem desfoque,
  sem sombra e sem os outros estados, em 0,56 s; a ficha fica escondida (`.zleve`) e o `mount` roda depois do voo. No PC, o efeito completo.
- Gráficos (v1.2): `lineChart` desenha na largura real do quadro (`lineSVG`, `LC_REG` + ResizeObserver), letras fixas, margem do eixo
  pelo tamanho dos números e rótulos do eixo X só os que cabem; grade `.lc-grade` e eixos `.lc-eixo`. Laterais (`linhasGraf`/`rankLinhas`)
  com W=400 e no máximo 1,15× de largura. Conteúdo centralizado em telas largas (`.page` até 1500px; 1720px acima de 2200px).
- Voltar (`NAVH`, `navVoltar`, `[data-voltar]`): páginas de detalhe (fora do menu) ganham "‹ Voltar para …" que volta à tela anterior na
  mesma rolagem; sem histórico, vai para a seção pai. Árvore dos escândalos no PC: tronco à esquerda e barras por fileira (sem curvas).
- Mapas: cor sólida por estado, divisas brancas, 5 faixas com o mesmo número de estados (`faixasDe`, `corFaixa`,
  `legFaixas` com os limites escritos). Nada de degradê entre estados. Eleições (presidente): modos "Quem venceu",
  "% de um candidato" e "Diferença entre os 2 primeiros" (escala divergente com empate em cinza).
- Gráficos: os 3 maiores em cor viva e os 3 menores em pastel (`rankPos`, `rankCor`).
- Tabelas: um padrão só (`table()`): 10 primeiras linhas + "Ver todos", ordenação ao tocar no título da coluna,
  cabeçalho fixo nas listas longas, números à direita.
- Formatos (v1.0): número em destaque = `.kpis/.kpi` ou pares `.facts` (blocos iguais, mesma letra em todo o site);
  comparação = barras (`hbars`, efetivo, eleições) com cores de `rankCor`; lista de registros = `table()`. CSS no bloco "v1.0".
- Maiores × menores: `rankDuplo(vals,fmt,{alto,baixo,corAlto,corBaixo})` — dois gráficos (5 maiores e 5 menores, 3 primeiros
  fortes e 2 apagados). Violência: mapa vermelho (`SCALE_VERM`), maiores em vermelho e menores em verde. Dívidas: mapa azul (`SCALE`) e maiores em `LIN_AZUL`.
- Projetos: situação via `camara-proposicoes-situacao` (arquivo anual da Câmara `proposicoes-AAAA.json`, campo
  `ultimoStatus`); no site `sitProj`/`sitProjTag` traduzem para palavras simples ("Aguardando votação", "Virou lei"…).
- Gráficos em linha (maiores × menores): `linhasDuplo(serie,anos,vals,fmt,…)` — 5 linhas por gráfico, 3 primeiras vivas e
  grossas, 2 apagadas; sem 2 anos de dados cai para `rankDuplo` (barras). Segurança usa `segHist` (histórico anual do
  `/seguranca`); dívida e arrecadação usam `/historico-estados` (anos coletados pelo robô: receita, tesouro e siconfi-divida).
- Barras de porcentagem (v1.3): `.bar` vira 10 quadradinhos arredondados (cada um = 10%, o do meio parcialmente cheio) por máscara
  CSS, 150 px de largura; as barras de comparação de `hbars` (`.hb-b`) continuam lisas. CSS no fim do `<style>` do site.
- Animação e período (v1.4; linhas em 2,6 s e barras em 1,8 s, para dar tempo de ver crescer; v1.7: pizzas `donut` e anéis `ring` (`.pz`) giram como ponteiro por máscara `.an-pz`, legenda `.an-f` linha a linha): gráficos (`.lc`, `svg.lr-svg`, `.hb`, `.bar`) ficam parados (`.an-pre`) até entrarem na tela
  (IntersectionObserver `AN_IO`) e então se montam (`.an-go`: linhas `.an-l` desenhadas, área `.an-a` revelada, pontos `.an-p`,
  barras crescendo); "reduzir movimento" desliga. `lineChart` reconhece anos/meses nos rótulos (ou `o.datas`) e mostra botões
  10 anos / 5 anos / 1 ano / 6 meses / Tudo (`LC_PER`, `lcCorte`; `o.per` = corte inicial em meses, `o.periodo:false` esconde);
  `serieChart` corta pelo calendário. `linhasDuplo` ganha 10 anos / 5 anos / Tudo (`LD_REG`). Só aparecem os botões que cortam algo.

## Polícias (out/2026)
- Fichas curadas em `app/dados/policias/<chave>.json` (`pm-UF`, `pc-UF`, `pf`, `prf`, `spf`, `fn`, `u-UF-SIGLA`): resumo, criação, marcos
  da história (inclusive chacinas e casos com a situação judicial da fonte), patrono e homenageados oficiais ("Heróis da farda"),
  organização (batalhões/delegacias com cidade), sede e efetivo — tudo com fonte; sem fonte é descartado (`app/policias.py`).
  API `/policias` e `/policias/{slug}`; site `#/policias` e `#/policia/<slug>` (`P.policias`, `P.policia`); brasões e linhas do
  efetivo na Segurança viram links (`polMarca`, `data-polgo`; `POL_ALIAS` para siglas repetidas).
- Contingente: Raio-X do FBSP (o mesmo da aba). Mortes por intervenção, presos por mandado e policiais mortos: Sinesp/Anuário do
  estado inteiro (não separam por corporação). Só o Rio publica por batalhão: coletor `isp-rj-batalhoes` (`app/collectors/isp_rj.py`,
  ISP por área AISP desde 2003) + tabela AISP → batalhão `aisp-RJ.json`; sempre com o aviso de que é "na área", não "pelo" batalhão.
- Atualizar a cópia: `python -m scripts.policias_copia [site/dados] [csv_do_isp]` (o robô exporta pelas FIXAS).
