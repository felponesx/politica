# Assistente local da IA própria (opcional)

A IA própria do BRASIL+ (`/ia/pergunta`) responde sozinha, sem modelo e sem custo. O assistente local é um **extra opcional**: um modelo
que roda no seu PC e só ajuda a **entender perguntas que as regras não entendem**. Ele escolhe o tipo da pergunta e as palavras citadas.
Quem consulta o banco e escreve os números é sempre o motor, nunca o modelo. Sem token, sem custo por pergunta, a pergunta não sai do PC.

## O que o seu PC aguenta (Xeon E3/E5, 32 GB, RX 580 8 GB)
Números abaixo são **relatos de comunidade, não medição no seu PC**; meça antes de decidir (passo 3).
- A RX 580 não tem suporte oficial no ROCm (a linha AMD do Ollama no Windows). O caminho que funciona é o **llama.cpp com Vulkan**.
- Modelos de 7 a 8 bilhões de parâmetros (quantização Q4) cabem nos 8 GB de vídeo e giram na casa de 8 a 24 palavras por segundo.
  Modelos menores (3 bilhões ou menos) são bem mais rápidos.
- Só pelo processador (sem a placa de vídeo) o relato para um Xeon parecido é perto de 3 palavras por segundo: use a placa.
- Para esta tarefa (devolver um JSON curto com o tipo da pergunta) basta um modelo pequeno; a resposta tem poucas dezenas de palavras.

## Passos
1. Descubra o que você tem (PowerShell):
   `Get-CimInstance Win32_Processor | Select-Object Name`
   `Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM`
2. Baixe do GitHub do llama.cpp (Releases) o pacote de Windows **com Vulkan** e um modelo `.gguf` de 3 a 8 bilhões de parâmetros com bom
   português, em Q4_K_M. Confira a licença do modelo que escolher.
3. Meça a velocidade na sua placa: `llama-bench.exe -m modelo.gguf -ngl 99`
4. Suba o servidor (só aceita o próprio PC): `llama-server.exe -m modelo.gguf --host 127.0.0.1 --port 8080 -ngl 99 -c 2048`
5. No `config.env` (pasta `BRASILMais`) ponha `MODELO_LOCAL_URL=http://127.0.0.1:8080` e reinicie o BRASIL+.
   Opcionais: `MODELO_LOCAL_NOME=` (o Ollama exige) e `MODELO_LOCAL_TIMEOUT=20` (segundos).
6. Teste com uma pergunta que as regras não entendem (abra no navegador):
   `http://127.0.0.1:8000/ia/pergunta?q=dos congressistas da legenda do PT quantos tem na câmara`
   Se o assistente ajudou, a resposta traz `"assistente": "modelo local"`.

## Garantias (cobertas por teste)
- Desligado se `MODELO_LOCAL_URL` estiver vazio. Só aceita endereço do próprio computador (127.0.0.1/localhost): a pergunta nunca sai da máquina.
- As regras tentam primeiro; o modelo só é chamado quando elas não entendem.
- A pergunta vai ao modelo como dado, com temperatura 0. Tipo fora da lista, texto que não é JSON, pessoa que não existe no banco, modelo
  fora do ar ou lento demais: tudo vira "não entendi", sem erro e sem executar nada.
- O modelo nunca vê o banco e nunca escreve a resposta.
