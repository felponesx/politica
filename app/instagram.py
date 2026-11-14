"""Conta do Instagram do BRASIL+ pela API oficial (Instagram API com login do Instagram). SÓ LEITURA: mostra a conta e as últimas
publicações. Não publica nada. Configuração (config.env): INSTAGRAM_TOKEN = token de acesso de longa duração da conta profissional.

O token vale 60 dias e precisa ser renovado; aqui só se avisa. O token nunca sai desta função (não vai para a resposta nem para o log)."""
from __future__ import annotations

import os
import time

import httpx

BASE = "https://graph.instagram.com/v21.0"
_cache: dict = {"em": 0.0, "dados": None}
PASSOS = [
    "Criar a conta profissional do BRASIL+ no Instagram",
    "Gerar o token e conectar ao sistema (INSTAGRAM_TOKEN no config.env)",
    "Publicar o primeiro post de teste (pelo aplicativo do Instagram)",
    "Ligar a publicação automática (ainda não existe neste programa)",
]


def _passos(feitos: list[bool]) -> list[dict]:
    return [{"texto": t, "estado": "feito" if feitos[i] else "pendente"} for i, t in enumerate(PASSOS)]


def _chamar(caminho: str, token: str, **params) -> dict:
    r = httpx.get(f"{BASE}/{caminho}", params={**params, "access_token": token}, timeout=20)
    if r.status_code == 401 or (r.status_code == 400 and "token" in r.text.lower()):
        raise PermissionError("o Instagram recusou o token (venceu ou foi revogado)")
    r.raise_for_status()
    return r.json()


def status(forcar: bool = False) -> dict:
    token = os.environ.get("INSTAGRAM_TOKEN", "").strip()
    if not token:
        return {"configurada": False, "conta": None, "publicacoes": [], "erro": None,
                "passos": _passos([False, False, False, False]),
                "aviso": "Sem INSTAGRAM_TOKEN no config.env, esta tela só mostra os passos que faltam. Nada é publicado por este programa."}
    if not forcar and _cache["dados"] is not None and time.time() - _cache["em"] < 300:
        return _cache["dados"]
    try:
        conta = _chamar("me", token, fields="user_id,username,account_type,media_count")
        midias = _chamar("me/media", token, fields="id,caption,media_type,permalink,timestamp,like_count,comments_count", limit=12)
        pubs = [{"id": m.get("id"), "legenda": (m.get("caption") or "")[:200], "tipo": m.get("media_type"), "link": m.get("permalink"),
                 "em": m.get("timestamp"), "curtidas": m.get("like_count"), "comentarios": m.get("comments_count")}
                for m in (midias.get("data") or [])]
        dados = {"configurada": True, "erro": None,
                 "conta": {"usuario": conta.get("username"), "tipo": conta.get("account_type"), "publicacoes": conta.get("media_count")},
                 "publicacoes": pubs, "passos": _passos([True, True, bool(pubs or conta.get("media_count")), False]),
                 "aviso": "Só leitura. O token vale 60 dias: renove antes de vencer. Este programa não publica no Instagram."}
    except PermissionError as e:
        dados = {"configurada": True, "conta": None, "publicacoes": [], "erro": str(e), "passos": _passos([True, False, False, False]),
                 "aviso": "Gere um token novo e troque INSTAGRAM_TOKEN no config.env."}
    except Exception as e:   # rede fora ou resposta inesperada: sem detalhe que possa conter o token
        dados = {"configurada": True, "conta": None, "publicacoes": [], "erro": f"não consegui falar com o Instagram ({type(e).__name__})",
                 "passos": _passos([True, False, False, False]), "aviso": "Tente de novo em instantes."}
    _cache.update(em=time.time(), dados=dados)
    return dados
