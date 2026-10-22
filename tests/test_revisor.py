"""Agente de revisão: pega número que não fecha, dado velho e lista de parlamentares acima das cadeiras."""
import json
from datetime import datetime, timedelta, timezone

from app.collectors.base import marcar_em_exercicio
from app.db import SessionLocal, criar_tabelas
from app.models import Parlamentar
from scripts import revisar_dados as rv

AGORA = datetime(2026, 10, 22, 15, 0, tzinfo=timezone.utc)


def _copia(tmp_path, dados: dict, gerado=AGORA):
    """Cópia mínima: um bloco s<N>.json por chave, com o mesmo hash do site."""
    blocos = {}
    for k, v in dados.items():
        blocos.setdefault(rv.fnv1a(k) % 128, {})[k] = v
    for n, d in blocos.items():
        (tmp_path / f"s{n}.json").write_text(json.dumps(d), encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({"versao": 1, "shards": 128, "gerado_em": gerado.isoformat()}), encoding="utf-8")
    return tmp_path


def _estados(pop=8e6):
    return {uf: {"pop": pop, "arr": 1e9, "gasto": 2e9} for uf in rv.UFS}


def _niveis(rel, titulo):
    return [i["nivel"] for i in rel["itens"] if titulo in i["titulo"]]


def test_dados_coerentes_passam(tmp_path):
    dados = {"/mapa/estados": {"estados": _estados()},
             "/seguranca": {"brasil": {"populacao": 216e6, "prisional": {"populacao": 1000, "populacao_celas": 700, "populacao_domiciliar": 300,
                                                                          "vagas": 600, "deficit_vagas": 100, "taxa_aprisionamento": 1000 / 216e6 * 1e5}}, "estados": {}},
             "/partidos/composicao": {"camara": {"partidos": {"A": 300, "B": 213}}, "senado": {"partidos": {"A": 81}}}}
    rel = rv.revisar(_copia(tmp_path, dados), AGORA, rede=False)
    assert _niveis(rel, "Mapa dos estados") == ["ok"] and _niveis(rel, "Cadeiras da Câmara") == ["ok"]
    assert _niveis(rel, "Presos: celas + domiciliar") == ["ok"] and _niveis(rel, "Cadeiras do Senado") == ["ok"]


def test_acima_das_cadeiras_e_conta_que_nao_fecha_viram_erro(tmp_path):
    dados = {"/mapa/estados": {"estados": {k: v for k, v in _estados().items() if k != "SP"}},
             "/seguranca": {"brasil": {"populacao": 216e6, "prisional": {"populacao": 1000, "populacao_celas": 500, "populacao_domiciliar": 300,
                                                                          "vagas": 600, "deficit_vagas": 100, "taxa_aprisionamento": 1}}},
             "/partidos/composicao": {"camara": {"partidos": {"A": 526}}, "senado": {"partidos": {"A": 86}}}}
    rel = rv.revisar(_copia(tmp_path, dados), AGORA, rede=False)
    assert _niveis(rel, "Mapa dos estados sem") == ["erro"]
    assert _niveis(rel, "Cadeiras da Câmara") == ["erro"] and _niveis(rel, "Cadeiras do Senado") == ["erro"]
    assert _niveis(rel, "Presos: celas + domiciliar") == ["erro"]
    assert rel["resumo"]["erro"] >= 4


def test_dados_velhos_e_arquivo_ausente(tmp_path):
    velho = AGORA - timedelta(days=10)
    (tmp_path / "noticias.json").write_text(json.dumps({"atualizado_em": (AGORA - timedelta(hours=20)).isoformat(), "itens": [
        {"titulo": "Notícia jur?dica quebrada", "link": "https://a", "data": AGORA.isoformat()},
        {"titulo": "Normal", "link": "https://a", "data": (AGORA + timedelta(days=3)).isoformat()}]}), encoding="utf-8")
    rel = rv.revisar(_copia(tmp_path, {}, gerado=velho), AGORA, rede=False)
    assert _niveis(rel, "Cópia completa") == ["erro"] and _niveis(rel, "Notícias: última") == ["erro"]
    assert _niveis(rel, "Contadores externos: arquivo ausente") == ["aviso"]
    assert _niveis(rel, "letras quebradas") == ["aviso"] and _niveis(rel, "data no futuro") == ["aviso"] and _niveis(rel, "Links de matéria repetidos") == ["aviso"]


def test_contador_contra_marco_noticiado(tmp_path):
    quando = AGORA - timedelta(minutes=5)
    ext = {"atualizado_em": quando.isoformat(),
           "impostometro": {"ao_vivo": {"base": 2.9e12, "quando": quando.isoformat(), "taxa": 130000.0}},  # menor que o marco de R$ 3 tri em 28/09
           "gastometro": {"ao_vivo": {"base": 4.63e12, "quando": quando.isoformat(), "taxa": 183000.0}}}
    (tmp_path / "contadores_externos.json").write_text(json.dumps(ext), encoding="utf-8")
    rel = rv.revisar(_copia(tmp_path, {}), AGORA, rede=False)
    assert _niveis(rel, "Impostômetro: total menor que o marco") == ["erro"]


def test_relatorio_e_gravavel_e_markdown_lista_os_erros(tmp_path):
    rel = rv.revisar(_copia(tmp_path, {}), AGORA, rede=False)
    json.dumps(rel)
    md = rv.markdown(rel)
    assert md.startswith("## Revisão dos dados") and rel["resumo"].keys() == {"erro", "aviso", "nao_verificado", "ok"}


def test_marcar_em_exercicio_tira_quem_saiu_e_protege_lista_cortada():
    criar_tabelas()
    with SessionLocal() as db:
        db.query(Parlamentar).filter(Parlamentar.casa == "casa-teste").delete()
        for i in "abc":
            db.add(Parlamentar(casa="casa-teste", id_externo=i, nome=i, em_exercicio=True))
        db.commit()
        assert marcar_em_exercicio(db, "casa-teste", {"a"}, minimo=3) == 0  # lista curta demais: nada muda
        assert marcar_em_exercicio(db, "casa-teste", {"a", "b"}, minimo=2) == 1
        db.commit()
        estado = {p.id_externo: p.em_exercicio for p in db.query(Parlamentar).filter(Parlamentar.casa == "casa-teste")}
        assert estado == {"a": True, "b": True, "c": False}
        db.query(Parlamentar).filter(Parlamentar.casa == "casa-teste").delete()
        db.commit()
