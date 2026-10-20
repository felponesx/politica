"""Configuração comum dos testes."""
import os

# todos os testes usam o mesmo cliente ("testclient"): sem isso o limite por IP (120/min) derruba os últimos testes
os.environ.setdefault("LIMITE_REQ_POR_MINUTO", "0")
