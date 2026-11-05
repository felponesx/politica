# O PC capta, guarda e mostra (Windows)

O PC faz tudo: coleta as fontes, confere com o Gemini, guarda no banco e roda o site.
O celular só acessa o sistema, pelo Tailscale.

## 1. Instalar (uma vez)
1. **Docker Desktop** (docker.com). Reinicie o PC quando pedir.
2. **Python 3.12** (python.org). Marque "Add python.exe to PATH".
3. **Git for Windows** (git-scm.com).
4. **Tailscale** (tailscale.com), com a mesma conta no PC e no celular.

## 2. Baixar o projeto
```powershell
cd $HOME\Documents
git clone https://github.com/felponesx/politica brasilmais
cd brasilmais
git checkout ingestao-coletor-celular
```

## 3. Chaves e senhas
- `copy .env.local.example .env.local` e preencha `DB_SENHA` e `DB_LEITURA_SENHA` (frases longas e diferentes).
- `copy coletor\.env.exemplo coletor\.env` e preencha `GEMINI_API_KEY`.
- Nunca use `API_BIND=0.0.0.0`.

## 4. Subir o banco, a API e o site
```powershell
docker compose -f docker-compose.local.yml --env-file .env.local up -d --build
```
O site abre em http://127.0.0.1:8000 no próprio PC.

## 5. Coleta automática (a cada 5 minutos)
```powershell
cd coletor
copy destinos.exemplo.toml destinos.toml
notepad destinos.toml
```
No `destinos.toml`, deixe só o destino de pasta, apontando para a pasta de dados do BRASIL+:
```toml
[[destino]]
nome = "PC"
tipo = "pasta"
pasta = "C:\\Users\\<seu-usuario>\\Documents\\brasilmais\\dados-pc"
```
Depois, no Agendador de Tarefas do Windows, crie uma tarefa a cada 5 minutos com o programa:
`python` e o argumento `coletor.py coletar`, com "Iniciar em" na pasta `coletor`. Crie outra tarefa, a cada 5 minutos,
com `coletor.py verificar` e outra com `coletor.py publicar` (ou troque o argumento para `coletar ; verificar ; publicar`).

## 6. BRASIL+ lendo os dados do PC
No `.env.local` (na pasta `brasilmais`), defina:
```
COLETOR_DADOS_PASTA=../coletor/dados-pc
```
Reinicie com o `docker compose ... up -d`. A ingestão roda sozinha a cada 10 minutos.

## 7. Acessar pelo celular
No PC: `tailscale serve --bg 8000`. Abra o endereço `https://...ts.net` no navegador do celular.

## Cuidados
- O PC precisa ficar ligado e sem suspensão (Configurações → Energia → "Nunca" para suspender quando conectado).
- Faça backup: a pasta `backups` guarda o banco todo dia. Copie para fora do PC de vez em quando.
