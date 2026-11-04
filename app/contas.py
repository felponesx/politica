"""Contas de pessoas para votar nas leis: cadastro, senha, sessão e CPF (só o código, nunca o número).

- Senha: scrypt com sal aleatório; guardado como "scrypt$n$r$p$sal$hash".
- CPF: conferido pelos dígitos verificadores e guardado só como HMAC-SHA256 com CPF_PEPPER (chave do servidor).
  Sem CPF_PEPPER o cadastro é recusado (falha fechada). O CPF digitado não comprova identidade: é só uma trava contra conta duplicada.
- Sessão: token aleatório no cookie HttpOnly; no banco fica só o SHA-256 do token.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Conta, Sessao

COOKIE = "bp_sessao"
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,}$")
OPCOES = ("aprovo", "nao_aprovo", "indeferido")
ROTULOS = {"aprovo": "Aprovo", "nao_aprovo": "Não aprovo", "indeferido": "Indeferido"}


class ErroConta(Exception):
    def __init__(self, mensagem: str, status: int = 400):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.status = status


def normalizar_email(email: str) -> str:
    return (email or "").strip().lower()


def email_valido(email: str) -> bool:
    return len(email) <= 254 and bool(EMAIL_RE.match(email))


def cpf_digitos(cpf: str) -> str:
    return re.sub(r"\D", "", cpf or "")


def cpf_valido(cpf: str) -> bool:
    d = cpf_digitos(cpf)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for tam in (9, 10):
        soma = sum(int(d[i]) * (tam + 1 - i) for i in range(tam))
        dv = (soma * 10) % 11 % 10
        if dv != int(d[tam]):
            return False
    return True


def _pepper() -> bytes:
    if not settings.cpf_pepper or len(settings.cpf_pepper) < 32:
        raise ErroConta("Cadastro indisponível: o servidor não está configurado (CPF_PEPPER).", 503)
    return settings.cpf_pepper.encode()


def codigo_cpf(cpf: str) -> str:
    return hmac.new(_pepper(), cpf_digitos(cpf).encode(), hashlib.sha256).hexdigest()


def hash_senha(senha: str) -> str:
    n, r, p = 2**14, 8, 1
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(senha.encode(), salt=sal, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${sal.hex()}${h.hex()}"


def confere_senha(senha: str, guardado: str) -> bool:
    try:
        _, n, r, p, sal, h = guardado.split("$")
        calc = hashlib.scrypt(senha.encode(), salt=bytes.fromhex(sal), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, bytes.fromhex(h))
    except (ValueError, TypeError):
        return False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def criar_sessao(db: Session, conta: Conta) -> str:
    token = secrets.token_urlsafe(32)
    db.add(Sessao(conta_id=conta.id, token_hash=_hash_token(token),
                  expira_em=datetime.utcnow() + timedelta(days=settings.sessao_dias)))
    db.flush()
    return token


def conta_da_sessao(db: Session, token: str | None) -> Conta | None:
    if not token:
        return None
    s = db.scalars(select(Sessao).where(Sessao.token_hash == _hash_token(token))).first()
    if s is None or s.expira_em < datetime.utcnow():
        return None
    return db.get(Conta, s.conta_id)


def encerrar_sessao(db: Session, token: str | None) -> None:
    if token:
        s = db.scalars(select(Sessao).where(Sessao.token_hash == _hash_token(token))).first()
        if s is not None:
            db.delete(s)


def email_mascarado(email: str) -> str:
    usuario, _, dominio = email.partition("@")
    return f"{usuario[:1]}***@{dominio[:1]}***"


def cadastrar(db: Session, email: str, senha: str, nome: str, cpf: str) -> Conta:
    email = normalizar_email(email)
    if not email_valido(email):
        raise ErroConta("E-mail inválido.")
    if not (8 <= len(senha) <= 128):
        raise ErroConta("A senha precisa ter entre 8 e 128 caracteres.")
    nome = " ".join((nome or "").split())
    if not (2 <= len(nome) <= 120):
        raise ErroConta("Informe o nome completo.")
    if not cpf_valido(cpf):
        raise ErroConta("CPF inválido. Confira os números.")
    codigo = codigo_cpf(cpf)  # também recusa se o servidor não tiver CPF_PEPPER
    if db.scalars(select(Conta).where((Conta.email == email) | (Conta.cpf_codigo == codigo))).first() is not None:
        # mensagem genérica: não revela se o e-mail ou o CPF já têm conta
        raise ErroConta("Não foi possível criar a conta. Confira os dados ou entre na conta existente.", 409)
    conta = Conta(email=email, senha_hash=hash_senha(senha), cpf_codigo=codigo, nome=nome)
    db.add(conta)
    db.flush()
    return conta


_HASH_REFERENCIA = hash_senha("referencia-sem-conta")


def entrar(db: Session, email: str, senha: str) -> Conta:
    conta = db.scalars(select(Conta).where(Conta.email == normalizar_email(email))).first()
    # sem conta, confere contra um hash de referência: o tempo de resposta não revela se o e-mail existe
    ok = confere_senha(senha, conta.senha_hash if conta else _HASH_REFERENCIA)
    if conta is None or not ok:
        raise ErroConta("E-mail ou senha incorretos.", 401)
    return conta
