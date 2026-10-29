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

## Carga completa mais curta (out/2026)
- `scripts/coleta_ci.py` (`VALIDADE`, `ja_coletada`): na carga completa (campo "tarefas" vazio), `siconfi-tributos` das cidades só roda de novo
  depois de 30 dias e `siconfi-despesas-funcao` de anos já fechados depois de 365 (o último ano fechado, 30); a conferência usa a tabela
  `coletas` do banco restaurado (status ok/parcial, mesmos parâmetros). Tarefas pedidas à mão sempre rodam. O passo "Fotos e logos" só refaz
  com o `indice.json` de `site/midia` mais velho que 7 dias (`midia-atrasada`, `MIDIA_DIAS`); pedindo `midia` nas tarefas, sempre refaz.
- Pelos horários do Actions (13/10): cidades do SICONFI 77 min, gerar a cópia do site de 22 min a 1h40 (ainda sem explicação) e fotos/logos 1 a 2 h.

## Contadores ao vivo e agente de revisão (out/2026)
- `app/collectors/contadores_externos.py` + `scripts/contadores_rapido.py` (no mesmo robô de 15 min, `noticias.yml`): leem os números do
  Impostômetro (ACSP) e do Gasto Brasil (CACB/ACSP) em gastobrasil.com.br (`/api/impostometro/brasil|uniao`, `/api/trpc/counters.spending`;
  a API do impostometro.com.br exige token e NÃO é usada — nunca guardar nem usar tokens que apareçam em respostas de terceiros) e gravam
  `site/dados/contadores_externos.json` já no formato de `/contadores` (total na hora publicada + ritmo por segundo em `ao_vivo`). `conferir` barra
  leitura com hora velha, União maior que o Brasil ou esferas que não somam o total. Com leitura de menos de 12 h ela vale sobre a conta
  própria e os marcos: no site (`snapContadores`; o medidor soma `ao_vivo.taxa` desde a leitura) e na API (`_externos` em `v03.py`; variável
  `CONTADORES_EXTERNOS` troca o arquivo, usada nos testes). Divisão do impostômetro: federal × estados+municípios (a do Impostômetro).
- `scripts/revisar_dados.py` + `.github/workflows/revisao.yml` (diário 09:23 UTC; aos domingos e com "urls" confere os links dos escândalos): agente de
  revisão determinístico sobre `site/dados` — frescor, somas que precisam fechar (população, arrecadação, presos, cadeiras, órgãos, dívida), contadores
  contra a fonte ao vivo e os marcos da imprensa, IBGE ao vivo, escândalos sem fonte, notícias quebradas. Grava `site/dados/revisao.json`, resumo na
  página da execução e falha com "erro". Não corrige nem prova que um número está certo. `exportar_snapshot` preserva `revisao.json`.
- `marcar_em_exercicio` (`base.py`): as listas atuais da Câmara (mín. 400) e do Senado (mín. 70) tiram `em_exercicio` de quem saiu; o revisor achou 526 deputados
  e 86 senadores "em exercício". Quem só aparece em votações entra como em exercício até a próxima coleta semanal de deputados.

## Fotos de candidatos e de envolvidos nos escândalos (out/2026)
- Prefeitos eleitos de 2024 (`fotos_prefeitos`/`fotos_prefeitos_de` em `scripts/midia_site.py`, chave `tse:<sq>`): cada foto vem do zip do TSE do estado
  (`foto_cand2024_UF_div.zip`, até 2 GB) por pedido Range, só os bytes dela (`_foto_do_zip` + `entradas_zip` de `bcb_scr.py`), a 200 px (WebP ~4 KB) para caber nos
  256 MB do Artifact (o site estava com ~204 MB antes dos prefeitos; o revisor avisa acima de 235 MB). Antes só entravam presidente, governador, senador e eleitos
  de 2022/2026. `python -m scripts.fotos_extra [site/midia] [site/dados]` acrescenta o que falta (prefeitos da lista da cópia dos dados + retratos oficiais) sem
  refazer o passo de horas e sem apagar nada.
- Envolvidos nos escândalos (`foto_camara`, `escolher_deputado` em `scripts/fotos_escandalos.py`): quem foi deputado federal ganha o retrato oficial da Câmara
  (`/deputados?nome=…&idLegislatura=45..57`, que lista também quem já saiu). Vale só com nome igual ao da pessoa (ou ao apelido entre parênteses), partido
  (siglas da mesma linhagem) e estado do cargo da época, e uma única pessoa depois dos filtros; na dúvida, sem foto. Vem antes da Wikipédia (que segue as
  regras de sempre). Quem não foi parlamentar (empresários, servidores, assessores) continua só pela Wikipédia; fotos enviadas à mão seriam o caminho.
- `revisar_dados` (grupo `midia`): tamanho do site e cobertura de fotos (prefeitos ≥ 90%, governadores, presidente, Congresso, escândalos).

## PC local e mudanças pelo celular (out/2026)
- Uso privado no PC do Felipe: `docker-compose.local.yml` (+ `.env.local`, ver `.env.local.example`): banco, agendador, API+site em `127.0.0.1:8000` e backup; o celular acessa
  pelo Tailscale (`tailscale serve --bg 8000`), nada exposto na internet. Guia em `docs/PC_LOCAL.md`. Repositório volta a ser privado; os robôs do GitHub deixam de ser necessários.
- `scripts/atualizar_local.py` (roda no PC, fora do Docker): confere o ramo principal a cada 5 min; se houver versão nova: `git merge --ff-only`, `docker compose build`, `pytest`
  dentro do Docker e só então `up -d --build`; se os testes reprovarem ou `/pronto` não responder, `git reset --hard` para o último bom (`.atualizador/ultimo_bom`), alerta
  (Telegram) e não repete a versão rejeitada (`.atualizador/rejeitado`). Recusa-se a mexer se houver arquivo alterado à mão. `.github/workflows/testes.yml` roda `pytest`
  em pull requests (aprovação pelo celular só com verde). Falta: passar ao `agendar.py` o que hoje só o robô do GitHub faz (eleições, segurança, notícias a cada 15 min, impostômetro,
  histórico, fotos) e adaptar `revisar_dados` ao banco local.

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
  grossas, 2 apagadas; sem 2 anos de dados cai para `rankDuplo` (barras; a antiga "linha ligando os estados" saiu). Segurança usa
  `segHist` (histórico anual do `/seguranca`); dívida e arrecadação usam `/historico-estados` (anos coletados pelo robô: receita,
  tesouro e siconfi-divida, 2015 em diante); famílias, `historico` do `/dividas/familias-estados` (SCR.data, último mês de cada ano:
  robô com `bcb-scr-estados ano=AAAA`); empresas, `por_uf_ano` do `/recuperacao-judicial/resumo` (acumuladas até cada ano).
- Impostômetro (`/contadores`): federal = soma das colunas do CSV da Receita (sem subtotais preenchidos desde 2000; 2025 = R$ 2,86 tri)
  no ritmo do ano; estados e prefeituras pelo RREO Anexo 03 em 12 meses; prefeitura sem relatório estimada pela média por habitante
  das cidades do mesmo estado e da mesma faixa de tamanho. Gastômetro divide o ano incompleto pelo tempo que os bimestres cobrem.
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

## Empresas × dívida (out/2026)
- Coleta `receita-empresas-porte` (`app/collectors/empresas_porte.py`): lê a base mensal do CNPJ (Estabelecimentos, Simples, Empresas,
  Cnaes) e os 3 arquivos da PGFN do último trimestre; conta as empresas ATIVAS (matriz) por porte (MEI pelo Simples, ME, EPP e
  "Demais" = médias e grandes juntas, porque a Receita não separa) e quantas têm dívida ativa da União (devedor principal, qualquer
  valor), recuperação judicial e falência; guarda as 300 que mais devem e as 300 de maior capital. API `/dividas/empresas`.
- Site: Dívidas › Empresas › aba "Endividamento" (`telaEmpresasDiv`, `empCard`): números do país, pizza por porte, % endividadas por
  porte, tabela somando tudo e separada, as que mais devem e as grandes que menos devem, ranking completo ordenável. Logo e resumo da
  Wikipédia em `logos.json` → `empresas` (`logos_empresas` em `scripts/midia_site.py`: só verbete {{Info/Empresa}} cujo título tem só
  palavras da razão social); sem verbete, a atividade principal do CNPJ. Robô: tarefas `receita-empresas-porte; midia`.

## Leveza (v1.9, out/2026)
- Cópia dos dados: 256 arquivos `s<N>.json` e respostas acima de 150 KB num arquivo só delas (`dados/g/<hash>.json`, com o marcador
  `{"__arquivo": "g/…"}` no shard; `snapLer` segue o marcador). `exportar_snapshot.py` (`gravar_partes`) já grava assim; para uma
  cópia pronta: `python -m scripts.reorganizar_copia site/dados`.
- Mídia: `logos.json` é só o índice; cada grupo (partidos, polícias, estados, veículos, empresas) fica em `logos_<grupo>.json` e o
  site baixa só o que a tela mostra (`midiaGrupo`). Logos e fotos em WebP quando fica menor (`scripts/logos_arquivo.py`: `ler`/`gravar`/`webp`).
  Fotos em 64 blocos (~0,5 MB); para refazer os blocos de uma cópia pronta: `python -m scripts.midia_site --reblocar site/midia`.
- Animações: linhas reveladas por uma cortina (`anCortina`, só transform) em vez de desenhar cada linha e cada ponto; tabelas e
  listas de porcentagem animam as barras juntas, em cascata (grupo `.tw`/`.pb` em `AN_GRUPO`).
- Tabelas (`table()`): só as 10 linhas visíveis entram na página; o resto fica em `TW_REG` e entra ao tocar em "Ver todos" (em pedaços
  de 400, `twCompleta`) ou ao ordenar. Clique na linha (`tr[data-href]`) é um ouvinte só para a página toda (`rowLinks` não faz mais nada).
- Porcentagens: `pbars(items)` — barra de bloquinhos (a mesma das tabelas) com o valor ao lado; usada nas Empresas (dívida por porte),
  eleições por partido, CAPAG por estado e demais listas em %. `hbars` fica para comparar valores (R$, quantidades, % acima de 100).
- Troca de aba nas Dívidas: `trocaSuave(el, html)` — o conteúdo antigo fica por cima e some enquanto o novo aparece (no mapa as cores
  passam de um tipo para o outro); `surgeSuave` para o detalhe. CSS no bloco "troca suave" (`.xf`, `.xf-velho`, `.xf-mapa`).
- Robô: `receita-empresas-porte` tem limite de 215 min em `LIMITES` (`scripts/coleta_ci.py`); com o limite padrão (45 min) a coleta parava no meio.

## Empresas e Contratos (out/2026)
- Abas (`ABAS_EMP`): Empresas (resumo de tudo: empresas do país, "como as empresas ganham e gastam", dívidas, contratos, maiores) · Dívidas
  (tudo o que era Dívidas › Empresas; `#/dividas/empresas` redireciona) · Maiores empresas (capital social, declarado e não conferido) ·
  Contratos públicos (pizzas de valor por esfera e de tamanho dos contratos, busca de CNPJ, lista de contratos, cruzamento fornecedores × cota).
- `ibge-empresas-economia` (`app/collectors/ibge_empresas.py`, API de agregados do IBGE, ano 2024): totais do país por setor (PIA-Empresa 10451,
  construção 10463, PAC 10645, PAS 10758: empresas, pessoal, receita, valor adicionado, gastos com pessoal). `GET /economia-empresas` deriva
  faturamento médio, gasto médio (compras + pessoal), margem = (valor adicionado − pessoal) ÷ receita (margem operacional bruta, NÃO lucro líquido),
  custo por pessoa e a repartição de cada R$ 100. Não existe faturamento por empresa em base aberta (só estes totais). `GET /resumo-contratos`:
  total, média, mediana, por esfera e por faixa de valor. As rotas não podem ficar sob `/empresas/…` nem `/contratos/…` (já têm `{documento}`/`{cid}`).
- Obras: o ObrasGov devolve `last: true` em toda página; `coletar_obras` só para em página curta (até 40 páginas por estado, estados em paralelo).

## Perfis de quem não é do Legislativo (out/2026)
- `#/indicado/<nome-sem-acento>` (`P.indicado`, janela flutuante): ministros de Estado, STF, STJ, TSE, TCU, STM e Banco Central, a partir das listas
  `NO_CARGO` e `MINISTROS` do site. Mostra quem é (resumo da Wikipédia em `site/midia/perfis.json`), como chegou ao cargo (quem indicou e o ano,
  quando a lista traz), desde quando e até quando (STF/STJ/TCU/STM: 75 anos, calculado pela data de nascimento do Wikidata; TSE: 2 anos; ministro de
  Estado: confiança do Presidente; BC: o mandato da lista). Não há base aberta de presença para ministros e juízes (o perfil diz isso).
  `scripts/perfis_indicados.py` (lê `app/dados/indicados_nomes.json`; roda no passo `midia` do robô) — ao mudar as listas no site, atualize esse JSON.
- Presidente, governadores e prefeitos (TSE) abrem o perfil de candidato (`#/candidato/<sq>`).
- Parlamentares: `GET /parlamentares/{id}/atuacao` ganhou `luta` (assuntos dos projetos de autoria, por palavras-chave) e `presenca`
  (votou em X das Y votações nominais dos últimos 12 meses); o Resumo mostra "O que defende" e "Presença nas votações".


## Saneamento e condições de vida no estado (out/2026)
- `ibge-saneamento` (`app/collectors/saneamento.py`): água (tabela 6803), esgoto (6805) e lixo (6892) do Censo 2022 por UF, luz da PNAD (9740) e
  população (9514); pessoas = % × população (estimativa). API `GET /saneamento`. A ficha do estado (Início) tem a seção "Saneamento, segurança
  e riscos" (`sanHtml`): % e número de pessoas com e sem cada serviço, segurança em 12 meses (total, por 100 mil, % da população) e desastres
  da Defesa Civil (`/riscos`) quando a planilha foi carregada. Alagamento por estado não existe em base aberta própria.

## Andamento das obras no perfil de quem governa (out/2026)
- `GET /obras-gestao?escopo=pais|uf|municipios&uf=` (`app/obras_gestao.py`): das obras com dinheiro federal do ObrasGov, % concluído (em número e em valor),
  o que falta, em andamento/paradas/não começaram, atraso (prazo previsto vencido em obra não concluída: quantidade, média e maior atraso, valor), próximo
  término e as obras atrasadas de maior valor. Presidente = país; governador = obras de executor estadual da UF; prefeito = executor "Prefeitura/Município de X"
  (chave = nome sem acento em maiúsculas). O robô exporta `pais`, `uf` e `municipios` por estado.
- Site: perfil do eleito (`#/candidato/<sq>`, só presidente/governador eleitos desde 2022 e prefeito desde 2024): quadro "Andamento das obras" no Resumo e aba
  "Obras e projetos". Sempre com o aviso: não é o plano de governo (não há base aberta que o acompanhe) e o percentual de execução física de cada obra não é aberto.

## Contadores ancorados nos números publicados (out/2026)
- `/contadores` (impostômetro e gastômetro) usa o último marco do ano de `app/dados/contadores_referencia.json` — Impostômetro (ACSP, impostometro.com.br:
  R$ 1 tri em 27/03/2026 e R$ 3 tri em 28/09/2026) e Gasto Brasil (CACB/ACSP, gastobrasil.com.br: R$ 3 tri em 15/07/2026, com divisão por esfera) — e
  calcula o ritmo (média desde 1º de janeiro até o marco). A conta própria (Receita + SICONFI) ficava ~14% acima do Impostômetro e sai em `calculo_proprio`.
  Para atualizar, acrescente um marco novo (data, valor, link da notícia) no JSON; sem marco do ano, volta a conta própria. Os sites de origem não abrem
  pelo ambiente do Claude (rede bloqueada): os marcos vêm de reportagens.

## Propostas de governo no perfil (out/2026)
- `scripts/propostas_resumo.py` (roda no passo `midia` do robô; à mão: `python -m scripts.propostas_resumo [site/midia] [site/dados] [ano…]`): baixa dos dados abertos do TSE
  (`proposta_governo_<ano>_<UF>.zip`, 2022 e 2026 inteiros; 2024 só as capitais, por pedido Range) o PDF de cada candidato a presidente, governador e prefeito, tira o texto
  com `pdftotext` e guarda até 3 trechos por tema (segurança, transporte, economia, saúde, educação, assistência e moradia, meio ambiente) em `site/midia/propostas.json`
  (`{sq: {ano, uf, paginas, legivel, temas}}`). Escolha por palavras-chave e verbos de ação; frase que cita quase todos os assuntos é descartada. É um resumo por trechos do
  próprio plano, sem avaliar nem conferir. PDF digitalizado (sem texto) fica `legivel: false`. O SQ varia de 11 a 12 dígitos e, em 2026, o arquivo tem sufixo `_01`.
- Site: quadro "O que propõe" no Resumo do `#/candidato/<sq>` (`propostasDe`, `propostasHtml`), 2 trechos por tema, com o aviso de que não confirma cumprimento.

## Fotos conferidas à mão (out/2026)
- Planilha do Felipe (22/10/2026, "pessoas_com_fotos_conferidas.xlsx"): 51 fotos de pessoas dos escândalos. `scripts/fotos_manuais.py importar <xlsx>` tira as 43 de
  retrato para `app/dados/fotos_manuais/` (WebP, com `fotos_manuais.json`: fonte e licença); 8 de grupo, montagem ou com texto por cima ficam de fora (`PULAR`:
  Cláudio Vieira, Dario Garcia Júnior, Marcelo Câmara, Marcelo Vieira, Marcos Soeiro, Osmar Crivelatti, Fernando Baiano, Léo Pinheiro) até haver um recorte só do rosto.
  O nome da chave `esc:<nome>` é o do caso (aba "Pessoas sem foto"), não o nome completo da galeria. `fotos_manuais()` entra no passo de fotos do robô (`midia_site`)
  e vale sobre a automática; `python -m scripts.fotos_manuais aplicar` coloca nos blocos de uma cópia pronta e grava `site/midia/creditos_fotos.json`, mostrado em
  "Créditos das fotos" no fim de cada caso. As miniaturas da planilha têm no máximo 155 px: uma versão maior melhoraria o avatar.


## Auditoria (out/2026) — leia `docs/RELATORIO_AUDITORIA.md` e `docs/FONTES.md`
- Limites compartilhados entre processos no banco (`app/limites.py`, tabelas `uso_limites`/`uso_ia`/`cache_ia`, migração 0007): requisições por IP
  (`Protecao` em `app/seguranca.py`), rotas pesadas e **todas as chamadas pagas da IA** (`app/ia_controle.py`: por IP, global, total do dia, orçamento
  em US$, concorrência, cache, registro sem conteúdo). Falha do contador: a IA bloqueia (503); o limite geral cai para balde local.
- IP do cliente só de `X-Forwarded-For` se a conexão vier de `PROXIES_CONFIAVEIS` (uvicorn roda com `--no-proxy-headers`). Corpo HTTP limitado no que chega (`LimiteCorpo`).
- Coletas: trava por tarefa no Postgres (`ColetaEmAndamento`), `abortada` após 12 h, retentativas com jitter e `Retry-After`. `GET /fontes/status`, `GET /pronto`, `GET /ia/uso`.
- Testes no Postgres: `sh scripts/testar_postgres.sh` (banco descartável; um banco sujo quebra testes). Dependências auditadas com `pip-audit` (fastapi 0.161, starlette 1.9).
- Site: faixa "Modo de demonstração" quando não há dados oficiais; painéis "Situação das fontes" e "Uso da IA" em Relatórios e Dados.

## Gastos de campanha no perfil do parlamentar (out/2026)
- `tse-contas` (`app/collectors/tse_financas.py`) conferida com o arquivo real do TSE (2022/SP): receitas por `DS_ORIGEM_RECEITA`, despesas contratadas por tipo e as 12 maiores
  por fornecedor (só CNPJ; CPF não é guardado). O zip traz também `receitas_candidatos_doador_originario_*` (não somar: contaria em dobro) e linhas vazias `#NULO` nas despesas.
  Migração 0008 (`despesas_fornecedores`). `GET /parlamentares/{id}/ligacoes` devolve `despesas_por_tipo` e `despesas_fornecedores` em cada candidatura.
- Site: aba Gastos do parlamentar tem "Gastos de campanha" (`campanhaHtml`) abaixo da cota. O robô roda `tse-contas` de 2002 a 2026 (menos 2004, sem código de candidato; `ELEICOES` em `scripts/coleta_ci.py`). O coletor lê os 3 leiautes do TSE (2018+, 2010–2016, 2002–2008: `_arquivos`, tuplas de colunas, chave composta `<UE>-<SQ>` de 2000 a 2008 igual à de `tse.py`) e só guarda candidaturas que já estão em `candidatos` (`todas=true` guarda tudo). Perfil do candidato (`#/candidato/<sq>`) também mostra os maiores fornecedores.

## Processos do parlamentar (out/2026)
- Aba "Processos" no perfil (`processosHtml`, `GET /parlamentares/{id}/processos`, `app/processos.py`): representações por quebra de decoro da Câmara (`REP` em `proposicoes`; o
  robô coleta `REP` no `HISTORICO`; liga só se o nome parlamentar for único na Câmara), candidaturas com registro não deferido (TSE) e casos curados (só nome completo igual ao da
  candidatura e sem outro parlamentar com o mesmo nome). Sempre com aviso de presunção de inocência. NÃO há processos por nome (STF/DataJud/TSE não têm base aberta que sirva; JusBrasil
  descartado): ver `docs/FONTES.md`. Processo em sigilo nunca aparece nem é inferido.

## Leis e Projetos (out/2026)
- Uma área só no menu (`#/leis/<aba>`, `P.leis`): Projetos de lei · Leis e normas (todas as normas / principais leis por assunto) · Constituição · Leis dos estados · Como uma lei nasce. Os endereços antigos
  (`#/projetos`, `#/legislacao`, `#/constituicao/...`) redirecionam. A aba "Leis federais" da Constituição virou "Principais leis por assunto" dentro de Leis e normas (não repete mais a lista).
- Projetos em cartões (`cartaoProjeto`): número grande; autor, relator, casa, data e situação pequenos; resumo (ementa); placar da última votação (A favor / Contra / Abstenções, placar oficial da casa ou
  contagem dos votos nominais; votação secreta só com o resultado). Filtro Para votar / Em votação agora / Já votados (`fase`). `GET /proposicoes` (`app/projetos.py`) devolve `autor`, `relator`
  (do texto da tramitação, só quando é uma designação), `placar`, `fase` e `na_pauta` (pauta dos eventos de hoje: `congresso-agenda`); REP (representações) fica fora da lista (aparece na aba Processos).
  Autor e relator só existem para quem teve a tramitação coletada (`camara-tramitacoes limite=…`; votadas primeiro). A pauta do dia só vale no dia da cópia (`pautaVale`).

## Dívidas numa seção só, setor financeiro e buscas (out/2026)
- Dívidas (`#/dividas/<tipo>`): pública, estados, cidades, famílias e **empresas** na mesma seção. Empresas tem 3 abas (`TELA_DIV.empresas`): Endividamento (números, ranking e pesquisa por nome/CNPJ/atividade/cidade, mais a inadimplência das empresas), Recuperação judicial e Falência
  (resumo por estado/porte/ano e pesquisa por nome ou CNPJ, `/recuperacao-judicial?q=`). A antiga aba Dívidas de Empresas e Contratos redireciona para cá.
- `bcb-financeiro` (`app/collectors/bcb_financeiro.py`): IF.data (balanço de dezembro e resultado = junho + dezembro, valores já em reais) + SGS do crédito (20539, 20540, 20541, 20631, 20622, 20714, 20783, 21082; o SGS só aceita
  "ultimos/N" até 20, por isso pede por datas). `GET /economia-empresas` traz `financeiro` (mesmas contas dos outros setores + `fatias` + maiores instituições + séries); o site mostra "Financeiro (bancos e crédito)" em Comparando setores.
- Maiores empresas: pesquisa (nome, CNPJ, atividade, cidade, UF, porte) sobre as 300 maiores. Contratos públicos: `GET /contratos?q=` (objeto, fornecedor, órgão, cidade, número ou CNPJ inteiro/começo).

## Arrecadação, Cortes e Dívidas simples (out/2026)
- Arrecadação e repasses: mapa com botões Arrecadação | Repasses (`/historico-estados` traz `arrecadacao` e `repasses`); lista "Todos os estados" compacta com ordem maior→menor (`listaUF`, também usada em Dívidas).
- Aba "Cortes de gastos" dentro de Órgãos (`#/orgaos/cortes`; `#/arrecadacao/cortes` redireciona; `telaCortes`, `GET /cortes`): corte = orçamento atualizado menor que o inicial por órgão (`transparencia-orcamento` de cada ano), não é contingenciamento. O robô exporta `/cortes` (FIXAS).
- Dívidas: quadro acima do mapa enxuto; Saúde fiscal mostra a CAPAG em palavras e cores (Forte/Boa/Fraca/Ruim = A/B/C/D) com tabela por ano (`/dividas/municipios` → `historico`, guardado em `capag_resumo`; rode `tesouro-capag url=…` com arquivos de outros anos para completar; arquivo antigo não sobrescreve a nota atual); Empresas tem aba Resumo (junta endividamento, recuperação e falência).
- As seções "Leis e Projetos" e "Empresas e Contratos" acima estão parcialmente desatualizadas (abas mudaram): vale a descrição no código (`ABAS_*`, `FASES_P`).

## Lista de 28/10 (out/2026)
- Órgãos: cada linha mostra o pago, o orçamento, a % usada em quadradinhos (`pct0`) e, quando há, o corte do ano (`/cortes` por código ou nome). Cortes de gastos: gráficos de linha (valor e % por ano), seletor de ano com pizza e lista órgão a órgão.
- `listaUF` (botão único de ordem `.ord-btn`) é a lista padrão por estado (Arrecadação, Dívidas, Indicadores). Dívidas › Empresas é uma página só (resumo, porte, recuperação/falência, maiores, pesquisas). Saúde fiscal: "CAPAG, ano a ano" e mais/menos em linhas.
- Indicadores: `IND_NOVOS` (bolsa, IPCA, Selic, salário mínimo, balança, PIB, dólar, desemprego), séries novas em `app/collectors/bcb.py` (`salario_minimo` 1619, `balanca_*` 22707–22709, `pib_var_anual` 7326; Ibovespa do Yahoo Finance `^BVSP`, porque o SGS parou em 2019). Sem mapa do país.
- Notícias › Fake news: feeds `tema="fake"` (Google Notícias filtrado por site .gov.br/.jus.br/.leg.br; só passa matéria de host oficial com termos de boato/desmentido). Escândalos e crimes: aba Crimes de políticos (`GET /crimes-politicos`, só condenações dos casos curados).
- PC: `html{zoom:.8}` acima de 1100 px (.76 acima de 1900 px) com `.side{zoom:1.25}` contrário (o menu mantém o tamanho original). Não pôr zoom num elemento interno: a lista nativa dos `<select>` abre no lugar errado. Candidatos: sem o mapa dos partidos.
- Limpeza (28/10): CSS e funções sem uso removidos (conferido por telas antes/depois, sem diferença). Ao procurar função sem uso, lembre que `...nome` (spread) conta como uso. A lista dos seletores (`posMenu`) abre para cima quando passaria da barra de atalhos do celular, e a barra (`.bnav`) fica em camada própria acima de tudo.
- Botões de seleção (`.pill`, `.pbar`): rótulo pequeno em cima, valor à esquerda embaixo, seta à direita, em todas as telas (bloco "botões de seleção" no fim do CSS, escopo `#view .pbar`; o "Mostrar" do mapa do Início fica em linha). Ao trocar um trecho do CSS por `s[:a]+novo+s[b:]`, confira que não apaga o que vem depois (isso já perdeu esse bloco uma vez).

## Lista de 29/10 (out/2026)
- Gastos › União: cartão corporativo (`transparencia-cartao`, `app/collectors/cartao.py`, `GET /cartao-corporativo`, 2015 em diante; o Portal devolve 405 em rajadas: espera entre downloads, meses
  antigos não são baixados de novo). Dívidas › Emendas parlamentares (`transparencia-emendas`, `GET /emendas`; sem dados a rota devolve 404). Indicadores › Impostos (`impostosHtml`, alíquotas).
- Comparar (antigo "Comparar" do menu): abas Regiões e Candidatos (presidentes, governadores, senadores e deputados, atuais e ex). Seletores de estado (`UFSel`, `data-pill="Estado"`) viram pílula com bandeira.
- Padrões novos: chave segmentada `.seg.sw` (Arrecadação/Repasses, Maiores/Menores); CAPAG em pílula colorida (`capagChip`); `.g3w` (3 colunas iguais no PC); `.cota-l`/`.nf-t` (gastos do parlamentar);
  `.mun-lado` (municípios do estado: cartões à esquerda, tabela à direita); `#ufReal .kpis` (4 por linha).
- Crimes de políticos: três visões — Condenados, Investigados com foro privilegiado (`_com_foro` em `app/escandalos.py`: só cargo ATUAL de senador/deputado federal → STF, governador → STJ; "ex-" e "candidato" ficam de
  fora) e Foragidos (`app/dados/foragidos.json`, `escandalos.foragidos()`: só com decisão judicial e fonte; quem saiu do país sem ordem de prisão não entra). Cópia: `python -m scripts.escandalos_copia` não cobre
  `/crimes-politicos`; regrave o shard com `escandalos.crimes()`.
- Prêmios (menu abaixo de Notícias; `P.premios`, `#/premios/<esporte>`; `P.premio` = janela com a história de um título, `#/premio/<chave>`): lista curada em `app/dados/premios.json` (títulos e medalhas do Brasil, com fonte
  por campeonato; ícones SVG em `PRM_IC`), `GET /premios` (`app/premios.py`); `python -m scripts.premios_wiki` busca na Wikipédia o resumo e a imagem de cada título
  (`app/dados/premios_wiki.json` + `site/midia/premios/*.webp`, texto CC BY-SA com link). `python -m scripts.premios_copia` grava `/premios` na cópia estática.
- Projetos: `prioridade` alta/média/baixa vem do regime de tramitação da Câmara (`Proposicao.regime`, migração 0009; Urgência = alta, Prioridade = média, Ordinária = baixa; MPV = alta) preenchido por
  `camara-proposicoes-situacao`; filtro `?prioridade=` em `GET /proposicoes`. Sem regime coletado, o cartão não mostra a etiqueta.
- Pendente: aba de votações dos tribunais (STF/STJ/TSE; não há base aberta: só casos curados com placar e fonte).
