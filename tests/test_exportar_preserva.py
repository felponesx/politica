"""A exportação da cópia não pode apagar pacotes gerados por outros scripts (p/...), só trocar o que ela mesma gera."""
import scripts.exportar_snapshot as ex


def test_regra_do_que_a_exportacao_recria():
    assert ex._e_da_exportacao("s12.json") and ex._e_da_exportacao("g/ab12.json") and ex._e_da_exportacao("manifest.json")
    assert not ex._e_da_exportacao("p/eleicoes.json") and not ex._e_da_exportacao("p/el-2014-presidente-1.json")
    assert not ex._e_da_exportacao("eventos.json")


def test_guarda_so_o_que_nao_e_da_exportacao(tmp_path):
    (tmp_path / "p").mkdir()
    (tmp_path / "p" / "eventos.json").write_text("{}", encoding="utf-8")
    (tmp_path / "s0.json").write_text("{}", encoding="utf-8")
    (tmp_path / "g").mkdir()
    (tmp_path / "g" / "x.json").write_text("{}", encoding="utf-8")
    assert set(ex._ler_fora_da_exportacao(tmp_path)) == {"p/eventos.json"}
    assert ex._ler_fora_da_exportacao(tmp_path / "nao-existe") == {}
