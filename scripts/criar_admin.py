"""Cria ou promove uma conta administradora, direto no servidor.

Uso (no servidor, com o banco configurado):
    python -m scripts.criar_admin dadosbrasilmais@gmail.com

A senha e o CPF são pedidos no terminal (não ficam no histórico de comandos nem no repositório).
Se a conta já existir, só recebe o papel de administrador (e, se pedido, uma senha nova).
"""
from __future__ import annotations

import getpass
import sys

from sqlalchemy import select

from app import contas
from app.db import SessionLocal
from app.models import Conta, agora_utc


def criar_ou_promover(db, email: str, nome: str, cpf: str | None, senha: str | None) -> str:
    """Devolve 'criada', 'promovida' ou 'atualizada'. Lança ValueError com a mensagem para o usuário."""
    email = contas.normalizar_email(email)
    if not contas.email_valido(email):
        raise ValueError("E-mail inválido.")
    conta = db.scalars(select(Conta).where(Conta.email == email)).first()
    if conta is not None:
        conta.papel = "admin"
        if senha:
            if len(senha) < 8:
                raise ValueError("A senha precisa ter pelo menos 8 caracteres.")
            conta.senha_hash = contas.hash_senha(senha)
            db.commit()
            return "atualizada"
        db.commit()
        return "promovida"
    if not cpf or not contas.cpf_valido(cpf):
        raise ValueError("CPF inválido.")
    if not senha or len(senha) < 8:
        raise ValueError("A senha precisa ter pelo menos 8 caracteres.")
    nome = " ".join((nome or "").split()) or email.split("@")[0]
    conta = Conta(email=email, senha_hash=contas.hash_senha(senha), cpf_codigo=contas.codigo_cpf(cpf), nome=nome[:120],
                  papel="admin", termos_versao=contas.TERMOS_VERSAO, termos_aceitos_em=agora_utc())
    db.add(conta)
    db.commit()
    return "criada"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Uso: python -m scripts.criar_admin <e-mail>")
        return 2
    email = argv[1]
    nome = input("Nome (se a conta for nova): ").strip()
    cpf = input("CPF (se a conta for nova, só números ou com pontos): ").strip()
    senha = getpass.getpass("Senha nova (mínimo 8 caracteres; deixe em branco para manter a atual): ")
    if senha and getpass.getpass("Repita a senha: ") != senha:
        print("As senhas não são iguais.")
        return 1
    db = SessionLocal()
    try:
        status = criar_ou_promover(db, email, nome, cpf or None, senha or None)
    except ValueError as e:
        print(f"Não foi possível: {e}")
        return 1
    finally:
        db.close()
    print({"criada": "Conta de administrador criada.", "promovida": "Conta existente agora é administradora.",
           "atualizada": "Conta administradora atualizada, com a senha nova."}[status])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
