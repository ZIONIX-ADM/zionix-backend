"""
Simula as 3 correções do motor de score e compara com os scores atuais no banco.
NÃO altera nada — só lê e calcula.
"""
import asyncio
import asyncpg
import os
from dotenv import load_dotenv

load_dotenv()
DB_URL = (os.getenv("DATABASE_URL") or "").replace("postgresql+asyncpg://", "postgresql://")

ATIVOS = ["PETR4", "ITUB4", "CXSE3", "VALE3"]


def suavizar(score_bruto: float, score_ontem: float | None) -> float:
    """
    Correção 1: suavização exponencial + cap de variação diária de 20 pts.
    """
    if score_ontem is None:
        return score_bruto  # primeiro dia: usa bruto

    suavizado = 0.65 * score_bruto + 0.35 * score_ontem

    # cap de ±20 pontos em relação a ontem
    delta = suavizado - score_ontem
    if abs(delta) > 20:
        suavizado = score_ontem + (20 if delta > 0 else -20)

    return round(suavizado, 1)


async def main():
    conn = await asyncpg.connect(DB_URL, ssl="require")

    print("=" * 68)
    print("COMPARATIVO: SCORE BRUTO (atual) vs SCORE CORRIGIDO (simulado)")
    print("=" * 68)

    for ticker in ATIVOS:
        rows = await conn.fetch("""
            SELECT data_referencia, score, decisao, sinal
            FROM scores_historico
            WHERE ticker = $1
              AND nao_elegivel = false
            ORDER BY data_referencia DESC
            LIMIT 7
        """, ticker)

        if not rows:
            print(f"\n{ticker}: sem dados no banco")
            continue

        # Do mais antigo para o mais recente
        rows = list(reversed(rows))

        print(f"\n{'─'*68}")
        print(f"  {ticker}  — últimos {len(rows)} dias")
        print(f"{'─'*68}")
        print(f"  {'DATA':<12} {'BRUTO':>6}  {'DECISÃO BRUTA':<16} {'SUAVIZADO':>9}  {'DELTA':>6}")
        print(f"  {'':─<12} {'':─>6}  {'':─<16} {'':─>9}  {'':─>6}")

        score_ontem = None
        for row in rows:
            data = row["data_referencia"].strftime("%d/%m/%Y")
            bruto = float(row["score"])
            decisao = row["decisao"] or "?"

            suavizado = suavizar(bruto, score_ontem)
            delta = suavizado - bruto if score_ontem is not None else 0.0
            sinal_delta = f"{delta:+.1f}" if score_ontem is not None else "  (1º dia)"

            print(f"  {data:<12} {bruto:>6.1f}  {decisao:<16} {suavizado:>9.1f}  {sinal_delta:>6}")
            score_ontem = suavizado  # próximo dia usa o suavizado como "ontem"

    print(f"\n{'═'*68}")
    print("CORREÇÃO 2 — CAP de 67 → penalidade gradual")
    print("  Antes: se entradaConfirmada=false → score ≤ 67 (hard cut)")
    print("  Depois: penalidade de 0, -5, -10 ou -15 pts dependendo de")
    print("          quantas das 3 condições (preço>MM50, MM9>MM21,")
    print("          fechamento verde) estão falhando.")
    print("  Efeito: scores altos com setup parcial caem ~5-10 pts,")
    print("          scores médios ficam iguais, não há teto artificial.")
    print()
    print("CORREÇÃO 3 — 'forca' por setor (hardcode)")
    print("  Antes: Financeiro=90, Varejo=35 etc → viés sistemático fixo")
    print("         Contribuição no score final: forca × 0.30 × 0.15 ≈ ±6 pts")
    print("  Depois: forca=50 para todos → contribuição zerada (neutro)")
    print("         Setores 'mais fortes' perdem até ~6 pts,")
    print("         setores 'mais fracos' ganham até ~6 pts → campo nivelado.")
    print(f"{'═'*68}")

    await conn.close()


asyncio.run(main())
