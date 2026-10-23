# Relatório da auditoria — BRASIL+ (23/10/2026)

Base: branch `claude/html-link-funcional-fabokf`. Classificação de cada item: **CT** = corrigido e testado ·
**CNV** = corrigido, mas não validado externamente · **PC** = parcialmente corrigido · **PD** = pendente.
Este relatório não declara o sistema "pronto para produção": veja a lista final do que ainda impede.

## 1. Linha de base e resultado dos testes
| | SQLite | PostgreSQL 16 |
|---|---|---|
| Antes (reproduzido no ambiente atual) | 123 passaram, 1 ignorado | não medido antes das mudanças (a primeira rodada no Postgres já tinha os limites novos: 144 passaram) |
| Depois | **157 passaram, 2 ignorados** | **159 passaram, 0 ignorados** |

Os ignorados no SQLite são testes que só existem no Postgres (busca em português, trava de coleta). Para rodar no Postgres:
`PGHOST=… PGPORT=… PGUSER=… sh scripts/testar_postgres.sh` (cria um banco descartável vazio; os testes deixam dados, então um banco sujo faz testes falharem).
`pip-audit -r requirements.txt`: **nenhuma vulnerabilidade conhecida** depois da atualização (antes: starlette 0.46.2 com vários avisos, pillow 11.3 e pytest 8 também com avisos).

## 2. Problemas encontrados (com evidência) e correções

### Custos da IA e limites (crítico)
| Problema | Evidência | Correção | Estado |
|---|---|---|---|
| Limite diário da IA em memória de cada worker (`_USO`) — com 2 workers valia o dobro e zerava a cada reinício | `app/ia_web.py`, `app/busca_web.py` (antes) | Contadores no banco (`uso_limites`), gasto atômico `INSERT … ON CONFLICT DO UPDATE … WHERE n+custo<=limite` (`app/limites.py`) | CT (3 processos Python reais disputando o mesmo contador: total = limite exato; reinício não zera) |
| Sem limite por pessoa, por minuto nem orçamento | idem | Por IP/minuto e por IP/dia, global/minuto, total do dia por rota e **orçamento diário estimado em US$** (`app/ia_controle.py`) | CT |
| Falha do contador poderia liberar chamadas | — | **Falha fechada**: sem contador, a IA responde 503 e não chama o provedor | CT |
| Sem teto de resposta, sem limite de concorrência, redirecionamento seguido | `ia_web.py` | `max_output_tokens` (padrão 1200), 4 chamadas simultâneas por processo, `follow_redirects=False`, resposta validada | CT (o parâmetro `max_output_tokens` da Agent API **não foi validado contra o provedor real**) |
| Cache só em memória | — | Cache compartilhado no banco (`cache_ia`, 1 h): a mesma pergunta não é cobrada duas vezes | CT |
| Sem registro de uso | — | `uso_ia`: quando, rota, hash do IP (HMAC, não é o IP), resultado, custo, ms — **sem pergunta nem resposta**; `GET /ia/uso` e painel em *Relatórios e Dados* | CT |
| Limite no provedor | — | Não é possível pelo código: **configure o teto de gasto no painel da Perplexity** (ação sua) | PD |

### Limitação de requisições e IP
| Problema | Correção | Estado |
|---|---|---|
| Balde em memória por processo (`Protecao._permitir`) | Contador compartilhado por IP/minuto; rotas pesadas (`/busca`, `/exportar`, `/ia/*`, `/obras-gestao/lista`) com limite próprio (20/min); `429` com `Retry-After` e `X-RateLimit-*`; se o banco cair, cada processo usa balde local (continua limitado) | CT |
| uvicorn `--forwarded-allow-ips "*"` confiava em `X-Forwarded-For` de qualquer um | `--no-proxy-headers`; IP real só vem de `X-Forwarded-For` quando a conexão é de rede listada em `PROXIES_CONFIAVEIS`, lendo da direita para a esquerda (falsificação à esquerda é ignorada); `X-Forwarded-Proto` idem | CT |
| Limite de corpo só olhava `Content-Length` | `LimiteCorpo` (ASGI) lê o corpo até o limite: 413 com chunked, sem `Content-Length` ou com valor mentiroso; `Content-Length` inválido = 400 | CT |

### Segurança da API
| Problema | Correção | Estado |
|---|---|---|
| Token admin sem limite de tentativas | 10 tentativas/min por IP (compartilhado), 429 depois | CT |
| `arquivo_local`/`pasta_local` aceitavam qualquer caminho do servidor | só dentro de `PASTA_ARQUIVOS_COLETA` (422 fora) | CT |
| CSV exportado executável no Excel (`=`, `+`, `-`, `@`) | apóstrofo na frente de texto perigoso | CT |
| Exportações pesadas sem teto de simultaneidade e sem validar parâmetros | máx. 3 simultâneas (503), `limite`/`ano`/`uf` validados | CT |
| Busca com byte NUL derrubava o Postgres (erro 500) | NUL removido | CT |
| Sem verificação de prontidão | `/saude` (vivo, sem consultas) e `/pronto` (banco + migrações em dia; só "ok"/503, detalhe vai para o log) | CT |
| Dependências vulneráveis | `fastapi 0.161`, `starlette 1.9`, `pillow 13`, `pytest 9` | CNV (testado em Python 3.13 local; o Docker usa 3.12 — rode a suíte na imagem antes de implantar) |
| SSRF | Já existia (`app/http.py`); **novo teste** prova que um site público redirecionando para `169.254.169.254` é barrado; `DNS rebinding` entre a checagem e a conexão continua um risco residual teórico | CT / risco residual |
| SQL injection | Nenhuma concatenação com entrada do usuário encontrada (busca usa `:q`/`:qlike`; nomes de tabela vêm de dicionário fixo); novos testes com `' OR 1=1 --`, `DROP TABLE`, `%`, `_`, `\`, NUL, emoji | CT |

### Banco e migrações
| Problema | Correção | Estado |
|---|---|---|
| Dois processos subindo juntos rodavam `alembic upgrade` ao mesmo tempo | `pg_advisory_xact_lock` na migração | CNV (lógica simples; não houve teste de corrida real) |
| Mesma coleta podia rodar duas vezes em paralelo | trava de aviso do Postgres por (fonte, tarefa, parâmetros), solta sozinha se o processo morrer | CT (Postgres) |
| Coleta "rodando" para sempre após queda | vira `abortada` após 12 h | CT |
| Novas tabelas | Migração `0007` (só cria 3 tabelas; `downgrade` as remove). No Postgres dá ao usuário `brasil_leitura` escrita **somente** nelas | CT (testado com o papel somente-leitura: escreve em `uso_limites`/`uso_ia`, e é barrado em `parlamentares`) |
| Integridade/duplicação | Já havia `UniqueConstraint(fonte,tipo,chave)` em `registros`, upsert idempotente e `atualizado_em`; nenhum dado histórico é apagado | verificado, sem mudança |
| N+1, índices, consultas lentas | Não encontrei evidência medida de gargalo nas rotas públicas além do já tratado na revisão anterior (cache, paginação, timeout de 30 s). **Não fiz um perfilamento com volume real** | PD |

### Coletores
Retentativas agora com **espera aleatória** e respeito a `Retry-After`; downloads grandes com timeout de leitura de 300 s (antes sem
limite); erros 4xx do cliente não são repetidos. Inventário completo e estado de cada fonte em `docs/FONTES.md`; saúde ao vivo em
`GET /fontes/status` e na tela *Relatórios e Dados*. Fontes **não rodadas**: PGFN, Defesa Civil; **configurada, não testada**: Portal da
Transparência (precisa de chave) e a pesquisa Perplexity (precisa de chave); **bloqueadas fora do Brasil**: LexML, ALMG.

### Demonstração × dados reais
Rastreei todas as 20 telas do menu com e sem dados: **com a cópia dos dados oficiais nenhuma tela mostra texto de demonstração**; **sem
dados**, todas dizem "dados demonstrativos" no rodapé e a etiqueta "Demonstração" no topo. Novo: **faixa amarela "Modo de demonstração"**
no alto de toda tela quando não há dados oficiais (antes, no celular só aparecia uma bolinha). Estado por área:

| Área | Estado | Fonte |
|---|---|---|
| Início/mapa, Gastos, Arrecadação, Dívidas, Órgãos, Pessoas, Eleições, Segurança, Empresas, Obras, Projetos, Legislação, Constituição, Escândalos, Notícias, Indicadores, Comparar, Agora | IMPLEMENTADO COM DADOS REAIS (cópia do robô) | ver `docs/FONTES.md` |
| Quadro societário (BrasilAPI) e riscos por cidade (Defesa Civil) | IMPLEMENTADO PARCIALMENTE: coletor existe, não validado contra a fonte real | BrasilAPI, Defesa Civil |
| Alagamento por estado | AGUARDANDO INTEGRAÇÃO: não existe base aberta própria | — |
| Pesquisa na internet da IA | IMPLEMENTADO PARCIALMENTE (código pronto; precisa de chave e do servidor no ar; nunca no site estático) | Perplexity |
| Dívida ativa da União, Defesa Civil | AGUARDANDO INTEGRAÇÃO (coletor existe, nunca rodou) | PGFN, Defesa Civil |

### Pesquisa unificada
Cobre parlamentares, candidatos, proposições, normas, votações, contratos, municípios e obras (as categorias realmente integradas; empresas
e órgãos têm busca própria nas telas). Acentos (unaccent), radical/plural (full-text `portuguese`), parte do nome, **erro de digitação em
nomes** (trigramas, novo), paginação com teto 50, entradas maliciosas. Testado no Postgres; no SQLite (desenvolvimento) a busca é `LIKE`
simples e **não ignora acentos**.

### IA
Regras novas no prompt: textos de notícias/páginas/resultados de busca são *dados, não instruções* (defesa contra injeção de prompt),
separar fato/estimativa/alegação/opinião, presunção de inocência, não inventar links nem citações, dizer quando falta evidência ou a
fonte está desatualizada. **Limite honesto:** isto é uma instrução ao modelo — reduz, mas não elimina o risco; não há teste automatizado
do comportamento do modelo.

### Interface/acessibilidade (parcial)
Faixa de demonstração, link "Pular para o conteúdo", contorno de foco visível, painéis novos em *Relatórios e Dados*. **Não** fiz uma
auditoria completa de contraste/leitor de tela. PC.

## 3. Arquivos modificados / criados
Novos: `app/limites.py`, `app/ia_controle.py`, `migrations/versions/0007_limites_e_uso_ia.py`, `tests/test_limites.py`,
`tests/test_auditoria.py`, `scripts/testar_postgres.sh`, `docs/FONTES.md`, `docs/RELATORIO_AUDITORIA.md`.
Alterados: `app/seguranca.py`, `app/ia_web.py`, `app/busca_web.py`, `app/busca.py`, `app/config.py`, `app/db.py`, `app/http.py`,
`app/main.py`, `app/models.py`, `app/collectors/base.py`, `app/routers/dados.py`, `app/routers/v03.py`, `scripts/exportar_snapshot.py`,
`Dockerfile`, `docker-compose.prod.yml`, `requirements.txt`, `site/index.html`, `tests/conftest.py` e testes ajustados.

## 4. Variáveis de ambiente novas (todas com padrão seguro)
`PROXIES_CONFIAVEIS` (no compose de produção: redes do Docker), `LIMITE_PESADO_POR_MINUTO` (20), `LIMITE_IA_IP_MINUTO` (4),
`LIMITE_IA_IP_DIA` (40), `LIMITE_IA_GLOBAL_MINUTO` (30), `IA_ORCAMENTO_DIA_USD` (5), `IA_CUSTO_CHAMADA_USD` (0,02),
`IA_CUSTO_BUSCA_USD` (0,005), `IA_CONCORRENCIA` (4), `IA_MAX_SAIDA_TOKENS` (1200), `IA_CACHE_SEGUNDOS` (3600), `IA_LOG_DIAS` (90),
`PASTA_ARQUIVOS_COLETA` (`./dados_locais`). Os custos por chamada são **estimativas suas** a ajustar com a fatura real.

## 5. Implantação e reversão
1. Faça backup (`infra/backup.sh`). 2. Atualize o código e rode a imagem nova (a API em produção tem `MIGRAR_AO_INICIAR=false`:
**rode a migração pelo agendador/`alembic upgrade head`** antes de subir a API; o `/pronto` falha enquanto o banco não estiver em `0007`).
3. Confira `PROXIES_CONFIAVEIS` com a rede Docker real (`docker network inspect`) — se ficar vazio, todos os visitantes parecem ter o IP do
Caddy e dividem um único limite. 4. Teste `GET /pronto`, `GET /ia/uso`, `GET /fontes/status`. 5. Defina o teto de gasto no painel da Perplexity.
Reversão: `alembic downgrade 0006` (apaga só as 3 tabelas novas; nenhum dado antigo é tocado) e volte à imagem anterior. O Caddyfile não mudou.

## 6. O que ainda impede a entrada em produção
1. Chave Perplexity e teto de gasto no provedor (e validar `max_output_tokens`) — **PD**.
2. Rodar a suíte e a API na imagem Docker (Python 3.12) com as dependências novas — **PD**.
3. Conferir `PROXIES_CONFIAVEIS` na rede real e testar limite com tráfego real atrás do Caddy — **PD**.
4. Perfilamento de desempenho com volume real de dados (N+1, índices) — **PD**.
5. Fontes nunca rodadas (PGFN, Defesa Civil) e Portal da Transparência (chave) — **PD**.
6. Auditoria de acessibilidade completa e revisão jurídica dos textos sobre escândalos — **PD**.
7. Backup: existe `infra/backup.sh`, mas **a restauração nunca foi testada** neste ambiente — **PD**.

## 7. Riscos residuais
Contadores no mesmo Postgres dos dados (uma carga alta nas rotas públicas gera escrita; se virar problema, migrar para Redis mantendo
a interface de `app/limites.py`); IP compartilhado (CGNAT) divide o limite entre pessoas; DNS rebinding teórico na barreira SSRF;
injeção de prompt não é eliminável só com instruções; custos são estimados, não medidos.
