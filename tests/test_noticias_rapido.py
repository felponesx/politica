"""Robô rápido de notícias: junção sem repetidas, escândalos citados e arquivo que não muda à toa."""
import json
from datetime import datetime, timedelta, timezone

from app.escandalos import casos_da_materia
from scripts import noticias_rapido

AGORA = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)


def _it(link, titulo, dias=0, resumo=""):
    return {"veiculo": "g1", "tema": "geral", "titulo": titulo, "link": link, "resumo": resumo,
            "data": (AGORA - timedelta(days=dias)).isoformat()}


def test_casos_da_materia():
    assert casos_da_materia("PF faz nova fase da operação sobre o Banco Master") == ["banco-master"]
    assert casos_da_materia("Caso Master chega ao STF") == ["banco-master"]
    assert casos_da_materia("Mastercard anuncia novo cartão") == []
    # o caso de nome mais longo vence o mais curto dentro do mesmo trecho
    assert casos_da_materia("Mensalão mineiro: Azeredo") == ["mensalao-mineiro"]
    assert casos_da_materia("Mensalão: Dirceu") == ["mensalao"]


def test_montar_junta_sem_repetir_e_tira_velhas_e_quebradas():
    antes = [_it("https://a", "Velha de verdade", dias=30), _it("https://b", "Segue valendo", dias=2),
             _it("https://c", "Notícia jur?dica quebrada", dias=1)]
    novas = [_it("https://b", "Segue valendo", dias=2), _it("https://d", "Operação Lava Jato volta ao STF")]
    itens = noticias_rapido.montar(antes, novas, AGORA)
    assert [i["link"] for i in itens] == ["https://d", "https://b"]  # mais nova primeiro; sem a velha nem a quebrada
    assert itens[0]["casos"] == ["lava-jato"] and itens[1]["casos"] == []


def test_arquivo_so_muda_quando_ha_noticia_nova(tmp_path, monkeypatch):
    feeds = [_it("https://x", "Senado vota reforma")]
    monkeypatch.setattr(noticias_rapido, "buscar_feeds", lambda: (feeds, ["Folha: ConnectError"]))
    feeds[0]["data"] = datetime.now(timezone.utc).isoformat()
    noticias_rapido.main([str(tmp_path)])
    arq = tmp_path / "noticias.json"
    primeiro = json.loads(arq.read_text(encoding="utf-8"))
    assert primeiro["total"] == 1 and primeiro["__completa"] and primeiro["atualizado_em"]
    assert primeiro["feeds_sem_resposta"] == ["Folha: ConnectError"]
    antes = arq.read_bytes()
    noticias_rapido.main([str(tmp_path)])  # nada novo: não reescreve (o robô não faz commit)
    assert arq.read_bytes() == antes


def test_sem_nenhum_feed_nao_apaga_o_que_existe(tmp_path, monkeypatch):
    (tmp_path / "noticias.json").write_text('{"itens":[1]}', encoding="utf-8")
    monkeypatch.setattr(noticias_rapido, "buscar_feeds", lambda: ([], ["g1: ConnectError"]))
    try:
        noticias_rapido.main([str(tmp_path)])
    except SystemExit as e:
        assert "Nenhum feed respondeu" in str(e)
    assert (tmp_path / "noticias.json").read_text(encoding="utf-8") == '{"itens":[1]}'
