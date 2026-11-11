# Instalar o BRASIL+ no PC principal (Windows)

O PC principal capta, confere, guarda e distribui os dados. O notebook e o celular só controlam, pelo Tailscale.

## Antes (uma vez)
Docker Desktop (aberto, "Engine running"), Python 3.12, Git e Tailscale instalados. O repositório clonado em `C:\Users\<você>\brasilplus`.

## Instalar
1. `git pull --ff-only origin ingestao-coletor-celular`
2. Duplo clique em `instalar\instalar-windows.cmd` (o Windows pede permissão de administrador).

O instalador:
- cria as senhas do banco e a chave do administrador em `.env.local` (não troca as que já existem);
- guarda a chave do Gemini em `coletor\.env` (ela não aparece na tela e fica só neste PC);
- cria `coletor\destinos.toml` e a pasta `coletor-dados`;
- agenda no Windows: o coletor a cada 5 minutos, o sistema ao entrar no Windows e um backup diário de `coletor\dados`;
- impede o PC de dormir na tomada;
- sobe o BRASIL+ e liga o acesso pelo celular.

Pode rodar de novo sem perder nada.

## Depois de instalar
- Painel: `http://127.0.0.1:8000/painel` (no celular, o endereço do Tailscale + `/painel`).
- Confira o Gemini: `cd coletor` e `py -3.12 coletor.py gemini-teste`. Se o nome do modelo não existir para a sua chave, ele lista os que existem; ponha o escolhido em `GEMINI_MODEL=` no `coletor\.env`.
- Cadastre fontes pelo painel (a chave do administrador é a linha `ADMIN_TOKEN` do `.env.local`).

## Coletor como programa (.exe)
`powershell -ExecutionPolicy Bypass -File instalar\construir-executavel.ps1` gera `coletor\coletor.exe`. A tarefa automática passa a usá-lo sozinha, sem precisar do Python. Ele guarda os dados ao lado dele, na mesma pasta de sempre.

## Desligar a coleta nativa que o coletor já faz
Depois de conferir que o coletor fez deputados e senadores direito, ponha no `.env.local`:
`NATIVAS_DESLIGADAS=camara-deputados,senado-senadores` e rode `docker compose -f docker-compose.local.yml --env-file .env.local up -d`.

## Arquivos que o instalador usa
`instalar\ciclo-coletor.ps1` (captar, conferir, publicar), `instalar\subir-sistema.ps1`, `instalar\backup-coletor.ps1`.
Log do ciclo: `coletor\ciclo.log`.

## Se algo falhar
Rode `docker compose -f docker-compose.local.yml --env-file .env.local logs api` e veja o `coletor\ciclo.log`.
