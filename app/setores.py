"""Setor de atividade a partir da CNAE (classe com 7 dígitos ou divisão com 2), nos mesmos grupos usados no site."""
SETORES = ["Tecnologia", "Construção civil", "Manutenção", "Trânsito e transporte", "Saúde", "Alimentação",
           "Limpeza e conservação", "Segurança", "Outros"]


def setor_de_cnae(cnae: str | None) -> str:
    c = "".join(ch for ch in str(cnae or "") if ch.isdigit())
    if not c:
        return "Outros"
    div, grupo = int(c[:2]), c[:4]
    if grupo in ("4644", "4645", "4664", "4771", "4773") or div in (21, 75, 86, 87, 88):
        return "Saúde"
    if div in (41, 42, 43, 71) and grupo != "4329" or grupo == "2330":
        return "Construção civil"
    if div in (58, 61, 62, 63) or grupo in ("4651", "4652", "9511"):
        return "Tecnologia"
    if div in (49, 50, 51, 52, 53) or grupo in ("7711", "7719", "4511", "4520", "4530"):
        return "Trânsito e transporte"
    if div in (10, 11, 56) or grupo in ("4631", "4632", "4633", "4634", "4635", "4637", "4639", "4721", "4729"):
        return "Alimentação"
    if div == 81 or grupo in ("3811", "3812", "3821", "3822", "3900"):
        return "Limpeza e conservação"
    if div == 80:
        return "Segurança"
    if div in (33, 95) or grupo in ("4329", "4322", "4321"):
        return "Manutenção"
    return "Outros"
