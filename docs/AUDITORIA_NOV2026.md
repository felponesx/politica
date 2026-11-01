# Auditoria BRASIL+ — 01/11/2026

Complementa `docs/RELATORIO_AUDITORIA.md` (23/10). Tudo abaixo foi medido nesta data; o que não deu para testar está dito.

## Como foi testado
- API local (uvicorn + SQLite) sondada com `curl`: rotas de escrita, CORS, cabeçalhos, `/docs`, rotas públicas de status.
- Postgres 16 descartável: migrações 0001→0013 do zero, usuário `brasil_leitura`, backup (`pg_dump`) e restauração em banco temporário.
- Playwright (Chromium): 37 telas com texto malicioso injetado nos dados (XSS); 31 telas × 7 resoluções (1920×1080, 1366×768, 1024×768, 768×1024, 430×932, 390×844, 360×800) medindo rolagem horizontal e elementos fora da tela; desempenho e erros em 31 telas.
- `pytest`: 313 passaram / 2 ignorados (SQLite) e 315 passaram (Postgres). `pip-audit`: nenhuma vulnerabilidade conhecida.

## Achados
| # | Gravidade | Achado | Estado |
|---|---|---|---|
| 1 | Alto | XSS: 6 telas (Agora, Gastos, Contratos, Segurança, Relatórios) executavam HTML vindo dos dados (fontes externas) por texto sem `esc()` | Corrigido nos pontos achados + defesa na entrada dos dados (`dadoLimpo`: `<` de início de tag e endereços `javascript:`). Reteste: 0 execuções em 37 telas |
| 2 | Médio | Mensagens de erro de coleta (`/coletas`, `/fontes/status`) públicas podiam mostrar chave/token, URL com parâmetros e caminhos do servidor | Corrigido (`app.limpeza.mascarar`) + testes |
| 3 | Médio | Backup sem conferência de integridade e com permissão padrão | Corrigido: `umask 077`, `gzip -t`, SHA-256 ao lado, retenção de 7; novo `infra/testar_restauracao.sh` (provado: restaura com a mesma contagem; arquivo adulterado é recusado) |
| 4 | Baixo | `/docs`, `/redoc` e `/openapi.json` públicos | `EXPOR_DOCS=false` em `docker-compose.prod.yml`; padrão continua ligado no desenvolvimento |
| 5 | Médio | 6 elementos vazando da tela (barras com valor em 768 px, legenda do hemiciclo em 1366, cartões de obras em 360) | Corrigido; reteste: 0 de 217 combinações com problema |
| 6 | Baixo | Links de texto com 14–20 px de altura no toque (Ver todos, Fontes, nomes) | Área de toque ampliada por `::after` (conferido por `elementFromPoint`: link de 20 px responde em 37 px) |
| 7 | Baixo | Aba Faculdades sem linha de fonte | Corrigido |

## O que foi verificado e está correto (com evidência)
- Só 3 rotas de escrita (`POST /coletas/{tarefa}`, `/ia/web`, `/busca/web`); sem token → 422; token errado → 401; depois de 10 erros por minuto → 429; token padrão/fraco → 403 (nunca libera). Não há login de usuário nem sessão nem cookie: a API pública é só leitura, por desenho.
- CORS só `GET` (pré-voo de `POST` de outra origem não anuncia `POST`, sem credenciais).
- Cabeçalhos: CSP (`frame-ancestors 'none'`, `object-src 'none'`, `connect-src 'self'`), `X-Frame-Options`, `nosniff`, `Referrer-Policy`, `Permissions-Policy`, COOP; HSTS quando a conexão é HTTPS.
- Nenhum segredo nos arquivos servidos ao navegador (`site/index.html` sem `Bearer`/`ADMIN_TOKEN`/`PERPLEXITY`); `.env*` ignorados pelo git; varredura de padrões de chave no repositório: nada.
- Banco: usuário da API só lê (INSERT/UPDATE/DELETE/DROP negados; escreve só nas 3 tabelas de limites); todas as tabelas têm chave primária; 12 chaves estrangeiras, todas com índice; `scram-sha-256`.
- Sem rolagem horizontal da página, sem erro de JavaScript e sem `undefined`/`NaN` visível nas 31 telas; popout fecha com Esc e no X.

## Riscos que continuam
1. **Sem contas de usuário/RBAC**: não há área administrativa no site; a única ação administrativa é o POST com token. Se um dia houver painel, precisa de autenticação nova (não existe hoje).
2. **CSP com `'unsafe-inline'`** (o site é um arquivo único com scripts e estilos embutidos): a defesa contra XSS depende de `esc()` + `dadoLimpo`. Só se resolve separando JS/CSS em arquivos e usando nonce/hash.
3. **Histórico de alterações**: `registros` guarda `atualizado_em`, mas não a versão anterior de cada dado; `coletas` registra cada execução. Não há tabela de auditoria de mudanças.
4. **Exclusão acidental**: `ON DELETE CASCADE` de `registros` para as tabelas normalizadas; só o dono do banco (agendador) pode apagar. Não há trava extra no banco.
5. **Backup só no mesmo servidor** (volume `backups`): sem cópia externa; a restauração foi provada em banco temporário, não no servidor de produção.
6. **Ampliar toque**: a conferência automática de "botões pequenos" mede o retângulo visível; a área ampliada por `::after` foi conferida só em um link.
7. **Site com 241 MB** (limite do Artifact: 256 MB): pouco espaço para crescer; `revisar_dados` avisa acima de 235 MB.
8. **DNS rebinding** entre a checagem e a conexão do coletor (SSRF) continua um risco teórico (já registrado em 23/10).
9. `/fontes/status` e `/ia/uso` são públicos (mostram situação das fontes e o gasto estimado da IA, sem segredo).

## Não testado / precisa de ação manual
- Teste de carga real e consultas lentas no Postgres com o volume de produção (medi só o navegador, em `localhost`, sem rede).
- Revisão visual quadro a quadro em todas as telas e resoluções: o teste automático acha vazamento, erro e alvo pequeno, não avalia beleza, gráficos deformados nem texto cortado dentro de caixas.
- Teste de restauração no servidor de produção e backup fora do servidor (ação sua).
- Teto de gasto da IA no painel do provedor (ação sua; ver relatório de 23/10).
- Telas sem linha de "Fonte" no texto: Maiores empresas, Polícias, Notícias (cada item tem a fonte própria, mas falta o rodapé padrão).
- Telas ainda sem dados: Saúde por município e Faculdades por cidade (aguardam coleta; o texto vazio explica).

## Classificação
- Segurança da API pública (somente leitura): **boa** nas verificações feitas; não é prova de ausência de falhas.
- Segurança do site contra XSS: **boa depois da correção**, com a ressalva do `unsafe-inline`.
- Responsividade (rolagem/vazamento): **sem falhas nas 217 combinações medidas**; qualidade visual fina não avaliada.
- Banco e backup: **bom**, com cópia externa pendente.
- Pronto para crescer nacionalmente: **ainda não** sem os itens 1–5 acima e um teste de carga.
