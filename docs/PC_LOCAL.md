# BRASIL+ no seu PC, privado, com mudanças pelo celular

Tudo roda no seu PC e só você acessa. O celular serve para **pedir mudanças ao Claude** e **cuidar do sistema**.

```
Celular (app Claude) ──pede a mudança──▶ Claude (nuvem) ──▶ ramo no GitHub ──você aprova──▶ main
                                                                                         │
PC: atualizar_local confere o ramo principal, roda os testes e só então reinicia ◀─────────────────┘
PC: agendador coleta ─▶ banco ─▶ API + site ──Tailscale──▶ site no celular
```

## 1. Instalar no PC (uma vez)
1. **Docker** (Docker Desktop no Windows/Mac; Docker Engine no Linux), **Git** e **Python 3.12**.
2. **Tailscale** no PC e no celular (mesma conta): é a rede privada que leva o site ao celular sem abrir nada na internet.
3. Baixe o projeto numa pasta **só para rodar** (não edite arquivos nela):
   - repositório privado: crie uma *deploy key* só de leitura (GitHub › Settings › Deploy keys) e use `git clone git@github.com:felponesx/politica.git`.
4. `cp .env.local.example .env.local` e preencha as senhas do banco (frases longas e diferentes). Opcional: chaves do Portal da Transparência,
   Perplexity e Telegram (para receber avisos no celular).

## 2. Subir o sistema
```
docker compose -f docker-compose.local.yml --env-file .env.local up -d --build
docker compose -f docker-compose.local.yml --env-file .env.local exec -d agendador python -m scripts.coletar inicial
```
O site abre em http://127.0.0.1:8000. A primeira carga leva horas; o agendador cuida do resto.

## 3. Ver o site no celular (privado)
No PC: `tailscale serve --bg 8000`. O Tailscale mostra um endereço `https://…ts.net`: abra no navegador do celular (logado no seu Tailscale).
Nunca coloque `API_BIND=0.0.0.0` no `.env.local`.

## 4. Mudanças pelo celular, sem quebrar nada
1. Peça a mudança ao Claude pelo app. Ele trabalha num **ramo** e abre um pedido de mudança (pull request).
2. No app do GitHub, confira se o teste (**Testes**) está verde e aprove (**Merge**). Só o que entra no ramo principal chega ao PC (hoje é `claude/html-link-funcional-fabokf`; o ideal é renomear para `main` em Settings › Branches). O atualizador segue o ramo que está aberto na pasta do PC.
3. O PC percebe em até 5 minutos, reconstrói, roda os testes **dentro do Docker** e só então reinicia. Se reprovar ou o sistema não subir,
   **volta sozinho para a versão anterior** e avisa no Telegram. A mesma versão ruim não é tentada de novo.

Deixe o atualizador sempre rodando (`python -m scripts.atualizar_local`), iniciando com o PC:
- **Windows:** Agendador de Tarefas › "Ao iniciar o computador" › `python -m scripts.atualizar_local` na pasta do projeto.
- **Mac:** `launchd` (um arquivo `.plist` com o mesmo comando) ou o app Automator ao iniciar sessão.
- **Linux:** um serviço `systemd` com `Restart=always` e o mesmo comando.

## 5. Cuidar do sistema pelo celular
| Quero saber | Onde |
|---|---|
| As fontes estão atualizadas? | Site › Relatórios e Dados › "Situação das fontes" (`/fontes/status`) |
| Uma coleta falhou? | Aviso no Telegram (3 falhas seguidas) e `/coletas` |
| O PC se atualizou? | Aviso "atualizado para …" no Telegram |
| Algo precisa de mão no PC | Claude Code no PC controlado pelo celular: no PC, `claude remote-control` na pasta do projeto |

## Cuidados
- PC ligado, sem hibernar, com internet. Se desligar, as coletas param e o site some (volta sozinho ao ligar).
- Backup diário do banco em `./backups` (guarda 7). Copie para fora do PC de vez em quando.
- Deixe o repositório **privado**. Nunca coloque senhas ou chaves no GitHub; elas ficam só no `.env.local`.
