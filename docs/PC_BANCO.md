# Banco do BRASIL+ no PC (Windows)

O PC guarda o banco, roda a API e o site, e faz as coletas. O celular só acessa, pelo Tailscale.

## 1. Instalar (uma vez)
1. **Docker Desktop** (docker.com) e reinicie o PC quando pedir.
2. **Git for Windows** (git-scm.com).
3. **Tailscale** (tailscale.com), entrando com a mesma conta no PC e no celular.

## 2. Baixar o projeto
Abra o PowerShell e rode:
```powershell
cd $HOME\Documents
git clone https://github.com/felponesx/politica brasilmais
cd brasilmais
git checkout ingestao-coletor-celular
```

## 3. Configurar as senhas
```powershell
copy .env.local.example .env.local
notepad .env.local
```
Preencha `DB_SENHA` e `DB_LEITURA_SENHA` com duas frases longas e diferentes.
**Nunca** coloque `API_BIND=0.0.0.0`.

## 4. Subir o banco, a API e o agendador
```powershell
docker compose -f docker-compose.local.yml --env-file .env.local up -d --build
```
O site abre em http://127.0.0.1:8000 no próprio PC.

## 5. Acessar pelo celular
No PC:
```powershell
tailscale serve --bg 8000
```
O Tailscale mostra um endereço `https://...ts.net`. Abra esse endereço no navegador do celular, com o Tailscale ligado.

## 6. Dados do celular
Clone o ramo de dados numa pasta do PC, para o BRASIL+ ler:
```powershell
git clone --branch dados-coletor --single-branch https://github.com/felponesx/politica coletor-dados
```
No `.env.local`, defina `COLETOR_DADOS_PASTA=coletor-dados`.

## 7. Atualização automática
Mantenha o `coletor-dados` atualizado com um agendamento a cada 5 minutos (Agendador de Tarefas do Windows):
`git -C coletor-dados pull -q --ff-only`

## Cuidados
- O PC precisa ficar ligado e sem suspensão. Se desligar, o site sai do ar, mas o celular continua captando e guardando no GitHub.
- Faça backup: a pasta `backups` guarda o banco todo dia. Copie para fora do PC de vez em quando.
