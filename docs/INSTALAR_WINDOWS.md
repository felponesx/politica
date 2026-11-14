# Instalar pelo instalador (recomendado)

1. No GitHub: **Actions > Instalador do Windows > Run workflow**, versao `1.0.0` (ou crie a tag `v1.0.0`). Leva ~15 min.
2. Em **Releases**, baixe `BRASILMais-Setup.exe`, de dois cliques e siga "Avancar" (nao pede administrador).
3. Marque "Abrir o BRASIL+ sozinho quando eu ligar o computador". O programa fica com um icone perto do relogio (Abrir o painel / Sair).
4. Seus dados ficam em `C:\Users\<voce>\BRASILMais` e nunca sao apagados ao instalar, atualizar ou desinstalar.
5. **Atualizacao automatica**: a cada 6 h o programa olha a Release mais nova, baixa, confere o SHA-256 e instala sozinho
   (fecha, troca e abre de novo). Para so avisar: `ATUALIZAR_AUTO=0` em `config.env`. Repositorio privado: ponha em `config.env`
   `ATUALIZAR_TOKEN=` com uma chave do GitHub so de leitura (Contents: Read) - nunca mande essa chave no chat.
6. Em outro computador/celular: abra pelo navegador o endereco do Tailscale do seu PC + `/painel`.

Abaixo, o metodo antigo com scripts (so para quem quiser gerar na propria maquina).

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

Diferença para a opção 2: o banco é SQLite. **Nomes** (políticos, municípios) a busca acha mesmo escritos errado, com ou sem acento (`Nicolas Ferrera` acha `Nikolas Ferreira`), nos dois bancos. **Textos** (leis, projetos, contratos): no PostgreSQL entende variações da palavra e ordena por relevância ("educação" acha "educacional"); no SQLite vira "contém o texto". Todo o resto funciona igual. Se a busca em textos for importante, use a opção 2 ou aponte o programa para um PostgreSQL com `DATABASE_URL=...` no `config.env`.


## Atualizar o sistema (um comando)
Toda vez que houver versao nova no GitHub, rode no PowerShell, na pasta do projeto:

```
powershell -ExecutionPolicy Bypass -File instalar\atualizar-e-subir.ps1
```

Ele baixa a versao nova, fecha o BRASIL+, gera o programa de novo e abre. As tabelas novas do banco (migracoes) sao criadas sozinhas na abertura.
Seus dados (`C:\Users\<voce>\BRASILMais`) nao sao tocados.

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

## Entrega automática dos dados ao GitHub (opcional)
No `config.env` do BRASIL+ (`C:\Users\<você>\BRASILMais\config.env`), coloque a pasta do clone do projeto:

    ENTREGA_GIT_PASTA=C:\Users\felip\brasilplus

A cada 6 h o programa gera `site/dados` com o banco dele e envia ao branch atual, só se houver mudança. Usa as credenciais de Git que o seu PC já tem. Para desligar, apague a linha.

Organizador de links (Gemini): ponha `GEMINI_API_KEY=` no `config.env` ou no `.env`, nunca no chat.


## Entrar no painel (`/painel`)
O painel tem login de verdade, com as mesmas contas do site (e-mail e senha). Papéis: **Administrador** (tudo, inclusive dar acesso), **Editor** (vê e cadastra fontes), **Leitor** (só vê) e conta comum (não entra). Cada pessoa pode ter permissões próprias por aba (Alterar, Ver ou Nenhum) na aba **Acessos**.

Para ser o primeiro administrador, escolha UM jeito:
1. Crie a sua conta no site e ponha o seu e-mail no `config.env`: `ADMIN_EMAILS=seu@email.com`. Feche e abra o BRASIL+ e entre no painel com esse e-mail.
2. Só para começar, sem conta: no `config.env` ponha `ADMIN_PADRAO=true` e entre com e-mail `admin` e senha `admin`. Essa conta de teste **para de valer sozinha assim que existir outro administrador**. Depois do passo 1, apague essa linha.

Quem não tem conta cria uma no site; depois o administrador procura o e-mail na aba **Acessos** e escolhe o papel.

## Instagram no painel (opcional, só leitura)
No `config.env` ponha `INSTAGRAM_TOKEN=` com o token de longa duração da conta profissional do BRASIL+ (Instagram API com login do Instagram). O painel mostra a conta e as últimas publicações. Ele **não publica** nada no Instagram. O token vale 60 dias: troque antes de vencer. Nunca mande esse token no chat.
