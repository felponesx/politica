import hashlib

import httpx
import pytest

from app import atualizador as at


def test_comparacao_de_versoes():
    assert at.e_mais_nova("1.0.0", "v1.0.1") and at.e_mais_nova("1.9.0", "2.0.0")
    assert not at.e_mais_nova("1.2.0", "v1.2.0") and not at.e_mais_nova("1.10.0", "1.9.9")
    assert at.tupla("v1.2") == (1, 2, 0)


def _cliente(conteudo: bytes, digest: str | None, sha_arquivo: str | None = None):
    sha = hashlib.sha256(conteudo).hexdigest()
    ativos = [{"name": at.INSTALADOR, "url": "https://api.github.com/a/1", "size": len(conteudo),
               **({"digest": f"sha256:{digest if digest is not None else sha}"} if digest != "" else {})}]
    if sha_arquivo is not None:
        ativos.append({"name": at.INSTALADOR + ".sha256", "url": "https://api.github.com/a/2"})

    def tratar(req: httpx.Request):
        u = str(req.url)
        if u.endswith("/releases/latest"):
            return httpx.Response(200, json={"tag_name": "v9.9.9", "assets": ativos})
        if u.endswith("/a/2"):
            return httpx.Response(200, text=sha_arquivo)
        return httpx.Response(200, content=conteudo)
    return httpx.Client(transport=httpx.MockTransport(tratar), follow_redirects=True)


def test_baixa_e_confere_hash(tmp_path):
    c = _cliente(b"instalador", None)
    info = at.consultar("x/y", "", c)
    assert info["tag"] == "v9.9.9"
    assert at.baixar(info, tmp_path, "", c).read_bytes() == b"instalador"


def test_hash_errado_descarta(tmp_path):
    c = _cliente(b"instalador", "0" * 64)
    with pytest.raises(ValueError, match="não confere"):
        at.baixar(at.consultar("x/y", "", c), tmp_path, "", c)
    assert not (tmp_path / at.INSTALADOR).exists()


def test_sem_hash_publicado_nao_instala(tmp_path):
    c = _cliente(b"instalador", "")
    with pytest.raises(ValueError, match="SHA-256"):
        at.baixar(at.consultar("x/y", "", c), tmp_path, "", c)


def test_hash_pelo_arquivo_sha256(tmp_path):
    conteudo = b"abc"
    c = _cliente(conteudo, "", hashlib.sha256(conteudo).hexdigest() + "  BRASILMais-Setup.exe")
    assert at.baixar(at.consultar("x/y", "", c), tmp_path, "", c).read_bytes() == conteudo


def test_verificar_fora_do_programa_instalado_nao_faz_nada():
    assert "só vale no programa instalado" in at.verificar()
