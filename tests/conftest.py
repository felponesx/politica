"""Configuração comum dos testes."""
import os

# todos os testes usam o mesmo cliente ("testclient"): sem isso o limite por IP (120/min) derruba os últimos testes
os.environ.setdefault("LIMITE_REQ_POR_MINUTO", "0")

# os testes de /contadores não podem depender do arquivo que o robô grava em site/dados (a leitura muda a cada 15 minutos)
os.environ.setdefault("CONTADORES_EXTERNOS", os.devnull + ".nao-existe")
