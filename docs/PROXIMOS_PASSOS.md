# Roteiro: quando o robô terminar (30/10/2026)

Pedido do Felipe: terminar a tabela de lacunas inteira e subir para o sistema (ramo `claude/html-link-funcional-fabokf`, de onde ele trabalha nas alterações do dia).

## Ordem
1. Robô #112 (`transparencia-social; transparencia-viagens; inpe-desmatamento; ibge-trabalho; tse-fundos; aneel-tarifas; tcu-inabilitados`, id 41000793086).
   - Terminou? `git fetch` + `git merge origin/claude/html-link-funcional-fabokf` (o robô commita a cópia lá) e ler `/coletas` em `site/dados` (shard do `/coletas?limit=30`).
   - Para cada tarefa com status `erro` ou `parcial`: ler o log do job com `tail_lines` pequeno (30–60), corrigir o coletor pela resposta real, adicionar a amostra real como teste.
2. Disparar o robô com as tarefas novas ainda não rodadas: `cnj-justica; anatel-banda-larga; anp-combustiveis` (mais as que falharam no passo 1, já corrigidas). Um robô por vez.
3. Quando o robô terminar: conferir os dados da cópia (`/trabalho`, `/justica`, `/social`, `/ambiente`, `/viagens`, `/fundos`, `/energia-tarifas`, `/tcu-inabilitados`, `/ensino`) — valores plausíveis, 27 estados, meses recentes. Número estranho: não publicar, anotar em `docs/FONTES.md` e avisar.
4. Rodar `pytest -q` inteiro, atualizar `CLAUDE.md` (trocar "NÃO conferido" por "conferido em AAAA-MM-DD" onde for o caso) e dar push nos dois ramos (`ccr-e76fd2d8-ihs61z` e `claude/html-link-funcional-fabokf`; fetch+merge antes, o robô commita lá).
5. Avisar o Felipe em português simples: o que entrou, o que foi conferido com dado real, o que ficou de fora e por quê.

## Sem fonte (não insistir sem novidade)
Servidores e salários (Portal 403), CAGED (timeout), renúncia fiscal (login), lista suja (404), TCU contas irregulares (sem arquivo), Querido Diário (520), ANAC (404), PRF (Google Drive), IGC (sem arquivo),
orientação da bancada na Câmara (vem vazia), doadores de campanha (CPF não é guardado), queimadas (130 MB/mês), IBAMA (403), escândalos novos (pesquisa curada, com fonte).
Se alguma voltar a responder, rodar `scripts/diag_pendentes*.py` pelo workflow `diag-pendentes*.yml` antes de escrever o coletor.

## Cuidados
- Logs do Actions: sempre `tail_lines` pequeno; o resultado de `list_workflow_runs` é enorme (use `per_page` 1–2).
- `tests/test_status_fontes.py` falha só quando rodado sozinho (banco de teste compartilhado): rode a suíte inteira.
- Nunca guardar CPF; só totais no TCU; avisos de presunção de inocência e de "aparecer em duas bases não indica irregularidade" ficam.
