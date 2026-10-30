"""Empresas punidas (CEIS, CNEP e acordos de leniência da CGU) e os contratos públicos que elas têm.

Cruzamento por CNPJ com os contratos coletados (PNCP e Portal da Transparência). Aparecer nos dois lugares NÃO indica irregularidade: a sanção pode valer só para o
órgão, a esfera ou o estado que a aplicou, e muitas já terminaram."""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Contrato, Registro

AVISO = ("Cadastros da CGU (Portal da Transparência): CEIS lista empresas impedidas de contratar com o poder público, CNEP lista multas da Lei Anticorrupção e os acordos de leniência "
         "são empresas que confessaram e devolveram dinheiro. Estar num cadastro não prova que um contrato específico foi irregular: a sanção pode valer só para o órgão, a esfera ou o "
         "estado que a aplicou, e muitas já terminaram. Só empresas (CNPJ) entram; pessoas físicas ficam de fora. Cada empresa tem direito de defesa.")


def resumo(db: Session) -> dict | None:
    r = db.scalar(select(Registro.dados).where(Registro.fonte == "cgu", Registro.tipo == "sancoes_resumo", Registro.chave == "BR"))
    return {**r, "aviso": AVISO, "fontes": ["CGU — CEIS, CNEP e Acordos de Leniência (Portal da Transparência)"]} if r else None


def empresa(db: Session, cnpj: str) -> dict | None:
    return db.scalar(select(Registro.dados).where(Registro.fonte == "cgu", Registro.tipo == "sancao_empresa", Registro.chave == cnpj))


def buscar(db: Session, q: str, limite: int = 30) -> list[dict]:
    q = (q or "").strip()
    if len(q) < 3:
        return []
    cond = Registro.chave.like(f"{''.join(c for c in q if c.isdigit())}%") if q.replace(".", "").replace("/", "").replace("-", "").isdigit() else Registro.titulo.ilike(f"%{q}%")
    linhas = db.scalars(select(Registro).where(Registro.fonte == "cgu", Registro.tipo == "sancao_empresa", cond).order_by(Registro.titulo).limit(limite)).all()
    return [{"cnpj": r.chave, "nome": r.titulo, "vigente": r.dados.get("vigente"), "cadastros": r.dados.get("cadastros"), "n": r.dados.get("n")} for r in linhas]


def _durante(contrato_data, sancoes: list[dict]) -> bool:
    if not contrato_data:
        return False
    d = contrato_data.isoformat()
    return any(s.get("inicio") and s["inicio"] <= d and (not s.get("fim") or d <= s["fim"]) for s in sancoes)


def contratos(db: Session, limite: int = 40) -> dict | None:
    """Empresas com sanção que têm contratos coletados, as de maior valor primeiro, e quantos contratos foram assinados durante uma sanção."""
    punidas = select(Registro.chave).where(Registro.fonte == "cgu", Registro.tipo == "sancao_empresa")
    linhas = db.execute(select(Contrato.cnpj_fornecedor, func.count(Contrato.id), func.coalesce(func.sum(Contrato.valor), 0.0), func.max(Contrato.fornecedor))
                        .where(Contrato.cnpj_fornecedor.in_(punidas)).group_by(Contrato.cnpj_fornecedor)
                        .order_by(func.coalesce(func.sum(Contrato.valor), 0.0).desc()).limit(limite)).all()
    total_emp = db.scalar(select(func.count(func.distinct(Contrato.cnpj_fornecedor))).where(Contrato.cnpj_fornecedor.in_(punidas)))
    if not total_emp and not db.scalar(select(func.count(Registro.id)).where(Registro.fonte == "cgu", Registro.tipo == "sancao_empresa")):
        return None
    itens = []
    for cnpj, n, total, nome in linhas:
        e = empresa(db, cnpj) or {}
        sancoes = e.get("sancoes") or []
        datas = db.scalars(select(Contrato.data_assinatura).where(Contrato.cnpj_fornecedor == cnpj)).all()
        itens.append({"cnpj": cnpj, "nome": e.get("nome") or nome, "contratos": n, "valor_total": round(total or 0, 2), "vigente": e.get("vigente"),
                      "contratos_durante_sancao": sum(1 for d in datas if _durante(d, sancoes)), "cadastros": e.get("cadastros"),
                      "sancao": (sancoes[0] if sancoes else None)})
    return {"empresas_com_contrato": total_emp or 0, "itens": itens, "aviso": AVISO}
