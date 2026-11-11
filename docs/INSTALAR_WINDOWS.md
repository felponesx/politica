# Instalar o BRASIL+ no PC principal (Windows)

O PC principal capta, confere, guarda e distribui os dados. O notebook e o celular só controlam, pelo Tailscale.

## Opção 1 (recomendada): programa único, sem Docker
Um programa (`BRASILMais.exe`) faz tudo: banco (SQLite embutido), captura, conferência com o Gemini, API, site e painel.

1. Precisa só do Python 3.12 (para gerar o programa) e do Tailscale (para o celular).
2. `git pull --ff-only origin ingestao-coletor-celular`
3. `powershell -ExecutionPolicy Bypass -File instalar\construir-tudo.ps1` (alguns minutos; gera `build-exe\dist\BRASILMais\BRASILMais.exe`).
4. Rode `BRASILMais.exe`. Na primeira vez ele cria sua pasta `C:\Users\<você>\BRASILMais`, a chave do administrador e pergunta a chave do Gemini (não aparece na tela).
5. Para abrir sozinho ao ligar o Windows: `BRASILMais.exe --iniciar-com-windows` (como administrador). No Windows, deixe o PC sem dormir na tomada.
6. Para o celular: `tailscale serve --bg 8000`.

**Backup:** todo dia às 3:30 o programa copia o banco e o manifesto do coletor (últimos 7 dias) e os arquivos originais captados (só acrescenta, nunca apaga) para `BRASILMais\\backups`. Como isso fica no mesmo disco, ponha em `config.env` `BACKUP_EXTRA=D:\\Backups\\BRASILMais` (disco externo ou pasta sincronizada com a nuvem) para ter uma segunda cópia.

Os dados (banco, configuração, vínculos, arquivos originais captados) ficam em `C:\Users\<você>\BRASILMais`, separados do programa: gerar o `.exe` de novo nunca apaga nada. Chaves e opções: `config.env` nessa pasta (a `ADMIN_TOKEN` é criada sozinha). O site completo (fotos e cópia dos dados) é copiado para `BRASILMais\site`.

Diferença para a opção 2: o banco é SQLite, e **a barra de busca fica mais fraca**. No PostgreSQL ela ignora acentos, entende palavras parecidas e ordena por relevância; no SQLite vira "contém o texto" (digitar `joao` não acha `João`). Todo o resto funciona igual (coletas, painel, cadastro de fontes, telas, API). Se a busca for importante, use a opção 2 ou aponte o programa para um PostgreSQL com `DATABASE_URL=...` no `config.env`.

## Opção 2: Docker + PostgreSQL (o que já estava)
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
