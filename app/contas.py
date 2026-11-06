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
from datetime import timedelta

import httpx

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Conta, Sessao, agora_utc

COOKIE = "bp_sessao"
TERMOS_VERSAO = "2026-11-05"  # troque quando os termos mudarem: quem já aceitou continua registrado com a versão antiga
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


def apagar_sessoes_vencidas(db: Session) -> None:
    """Sessões vencidas não servem para nada: são apagadas a cada novo login (o banco não cresce sem fim)."""
    db.query(Sessao).filter(Sessao.expira_em < agora_utc()).delete(synchronize_session=False)


def criar_sessao(db: Session, conta: Conta) -> str:
    token = secrets.token_urlsafe(32)
    db.add(Sessao(conta_id=conta.id, token_hash=_hash_token(token),
                  expira_em=agora_utc() + timedelta(days=settings.sessao_dias)))
    db.flush()
    return token


def conta_da_sessao(db: Session, token: str | None) -> Conta | None:
    if not token:
        return None
    s = db.scalars(select(Sessao).where(Sessao.token_hash == _hash_token(token))).first()
    if s is None or s.expira_em < agora_utc():
        return None
    return db.get(Conta, s.conta_id)


def encerrar_sessao(db: Session, token: str | None) -> None:
    if token:
        s = db.scalars(select(Sessao).where(Sessao.token_hash == _hash_token(token))).first()
        if s is not None:
            db.delete(s)


GOOGLE_TOKENINFO = "https://oauth2.googleapis.com/tokeninfo"
GOOGLE_EMISSORES = ("accounts.google.com", "https://accounts.google.com")


def admins_configurados() -> set[str]:
    return {normalizar_email(e) for e in (settings.admin_emails or "").split(",") if normalizar_email(e)}


def aplica_papel(conta: Conta) -> None:
    """Quem está em ADMIN_EMAILS vira administrador ao entrar. Tirar o e-mail da lista não rebaixa sozinho (fica a decisão no banco)."""
    if conta.email in admins_configurados() and conta.papel != "admin":
        conta.papel = "admin"


def e_admin(conta: Conta | None) -> bool:
    return conta is not None and conta.papel == "admin"


def verificar_google(credencial: str) -> dict:
    """Confere o ID token do Google com o próprio Google (tokeninfo, por HTTPS): emissor, público (nosso cliente), validade e e-mail confirmado."""
    if not settings.google_client_id:
        raise ErroConta("Entrar com o Google não está configurado neste servidor.", 503)
    if not credencial or len(credencial) > 4096:
        raise ErroConta("Login do Google inválido.", 401)
    try:
        r = httpx.get(GOOGLE_TOKENINFO, params={"id_token": credencial}, timeout=8)
    except httpx.HTTPError:
        raise ErroConta("Não foi possível falar com o Google agora. Tente de novo.", 503)
    if r.status_code != 200:
        raise ErroConta("Login do Google recusado. Entre de novo.", 401)
    c = r.json()
    if c.get("aud") != settings.google_client_id or c.get("iss") not in GOOGLE_EMISSORES:
        raise ErroConta("Login do Google recusado. Entre de novo.", 401)
    if str(c.get("email_verified", "")).lower() != "true" or not c.get("sub") or not c.get("email"):
        raise ErroConta("Use uma conta Google com e-mail confirmado.", 401)
    try:
        if int(c.get("exp", 0)) < int(agora_utc().timestamp()):
            raise ErroConta("Login do Google expirou. Entre de novo.", 401)
    except (TypeError, ValueError):
        raise ErroConta("Login do Google recusado. Entre de novo.", 401)
    return {"sub": str(c["sub"]), "email": normalizar_email(c["email"]), "nome": " ".join(str(c.get("name") or "").split())}


def conta_do_google(db: Session, claims: dict) -> Conta | None:
    """Conta já ligada a este Google; se não houver, a conta com o mesmo e-mail (já confirmado pelo Google) passa a usar o Google."""
    conta = db.scalars(select(Conta).where(Conta.google_sub == claims["sub"])).first()
    if conta is None:
        conta = db.scalars(select(Conta).where(Conta.email == claims["email"])).first()
        if conta is not None:
            if conta.google_sub and conta.google_sub != claims["sub"]:
                raise ErroConta("Este e-mail já está ligado a outra conta Google.", 409)
            conta.google_sub = claims["sub"]
    if conta is not None:
        aplica_papel(conta)
    return conta


def cadastrar_google(db: Session, claims: dict, cpf: str, aceite_termos: bool) -> Conta:
    if aceite_termos is not True:
        raise ErroConta("Para criar a conta, leia e aceite os termos de uso e de privacidade.")
    if not cpf_valido(cpf):
        raise ErroConta("CPF inválido. Confira os números.")
    codigo = codigo_cpf(cpf)
    nome = claims.get("nome") or claims["email"].split("@")[0]
    nome = " ".join(nome.split())[:120]
    if len(nome) < 2:
        raise ErroConta("Informe o nome completo.")
    if db.scalars(select(Conta).where((Conta.email == claims["email"]) | (Conta.cpf_codigo == codigo) | (Conta.google_sub == claims["sub"]))).first() is not None:
        raise ErroConta("Não foi possível criar a conta. Confira os dados ou entre na conta existente.", 409)
    conta = Conta(email=claims["email"], senha_hash=None, google_sub=claims["sub"], cpf_codigo=codigo, nome=nome,
                  termos_versao=TERMOS_VERSAO, termos_aceitos_em=agora_utc())
    aplica_papel(conta)
    db.add(conta)
    db.flush()
    return conta


def email_mascarado(email: str) -> str:
    usuario, _, dominio = email.partition("@")
    return f"{usuario[:1]}***@{dominio[:1]}***"


def cadastrar(db: Session, email: str, senha: str, nome: str, cpf: str, aceite_termos: bool = False) -> Conta:
    if aceite_termos is not True:
        raise ErroConta("Para criar a conta, leia e aceite os termos de uso e de privacidade.")
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
    conta = Conta(email=email, senha_hash=hash_senha(senha), cpf_codigo=codigo, nome=nome,
                  termos_versao=TERMOS_VERSAO, termos_aceitos_em=agora_utc())
    aplica_papel(conta)
    db.add(conta)
    db.flush()
    return conta


_HASH_REFERENCIA = hash_senha("referencia-sem-conta")


def entrar(db: Session, email: str, senha: str) -> Conta:
    conta = db.scalars(select(Conta).where(Conta.email == normalizar_email(email))).first()
    # sem conta, confere contra um hash de referência: o tempo de resposta não revela se o e-mail existe
    ok = confere_senha(senha, conta.senha_hash if conta and conta.senha_hash else _HASH_REFERENCIA)
    if conta is None or conta.senha_hash is None or not ok:
        raise ErroConta("E-mail ou senha incorretos.", 401)
    aplica_papel(conta)
    return conta
