"""
Batch diário de scores — roda após fechamento da B3 (18h30, seg-sex).
Lê tickers_b3.json, calcula score para cada ativo e persiste no Supabase.
"""

import asyncio
import json
import os
import time
import ssl
import urllib.request
from datetime import date

import asyncpg
import yfinance as yf
from dotenv import load_dotenv

from main import (
    # analisar_ativo mantida em main.py para comparação futura — não usada no batch
    calcular_drawdown_maximo,
    traduzir_setor,
    verificar_confiabilidade,
    verificar_historico,
)

load_dotenv()

DB_URL = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")
NEXTJS_URL = os.getenv("NEXTJS_URL", "http://localhost:3000")
TICKERS_FILE = "tickers_b3.json"
BATCH_SIZE = 10
SLEEP_ENTRE_BATCHES = 2  # segundos


def sinal_from_score(score: float) -> str:
    if score >= 70:
        return "Compra forte"
    if score >= 55:
        return "Compra"
    if score >= 45:
        return "Aguardar confirmação"
    if score >= 30:
        return "Cautela"
    return "Evitar"


def chamar_motor_ts(precos, highs, lows, datas, mercado, setor) -> dict:
    """POST para /api/score (motor TS gerarDiagnosticoDiario). Retorna {score, decisao}."""
    payload = json.dumps({
        "precos": precos,
        "highs": highs,
        "lows": lows,
        "datas": datas,
        "mercado": mercado,
        "setor": setor,
    }).encode()
    req = urllib.request.Request(
        f"{NEXTJS_URL}/api/score",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    # ssl_ctx: no Railway (Linux) os certs sistema funcionam normalmente.
    # Em macOS dev, python.org installer não configura certs — create_default_context
    # com cafile do certifi resolve sem desabilitar verificação.
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
        return json.loads(resp.read())


def calcular_score_ativo(ticker_sa: str, mercado: str = "neutro"):
    """Calcula score via motor TS. Retorna dict com todos os campos para o banco."""
    try:
        empresa = yf.Ticker(ticker_sa)
        info = empresa.info

        nome = info.get("longName") or info.get("shortName") or ticker_sa.replace(".SA", "")
        setor = traduzir_setor(info.get("sector") or "")
        preco_raw = info.get("currentPrice")

        historico = empresa.history(period="2y")
        if historico.empty:
            return {"erro": "sem dados"}

        motivo_bloqueio = verificar_historico(historico)
        if motivo_bloqueio:
            return {
                "nao_elegivel": True,
                "motivo_bloqueio": motivo_bloqueio,
                "nome": nome,
            }

        avisos = verificar_confiabilidade(historico, historico["Close"].iloc[-1])
        historico = historico.tail(252)

        preco_atual = historico["Close"].iloc[-1]
        preco_anterior = historico["Close"].iloc[-2] if len(historico) >= 2 else preco_atual
        variacao_percentual = ((preco_atual - preco_anterior) / preco_anterior * 100) if preco_anterior else 0

        preco_inicio = historico["Close"].iloc[0]
        tendencia = "alta" if preco_atual > preco_inicio else "queda"

        variacoes = historico["Close"].pct_change().dropna()
        vol = variacoes.std() if not variacoes.empty else 0
        if vol > 0.03:
            volatilidade = "alta"
        elif vol > 0.015:
            volatilidade = "moderada"
        else:
            volatilidade = "baixa"

        sequencia = 0
        for i in range(len(historico) - 1, 0, -1):
            if historico["Close"].iloc[i] > historico["Close"].iloc[i - 1]:
                sequencia += 1
            else:
                break

        # contexto derivado localmente (mesma lógica do legado)
        if tendencia == "alta" and sequencia >= 3:
            contexto = "tendencia_forte"
        elif tendencia == "alta":
            contexto = "pullback"
        elif tendencia == "queda":
            contexto = "bearish"
        else:
            contexto = "neutro"

        precos_list = [round(float(x), 2) for x in historico["Close"].tolist()]
        highs_list  = [round(float(x), 2) for x in historico["High"].tolist()]
        lows_list   = [round(float(x), 2) for x in historico["Low"].tolist()]
        datas_list  = [d.strftime("%d/%m") for d in historico.index]

        analise = chamar_motor_ts(
            precos=precos_list,
            highs=highs_list,
            lows=lows_list,
            datas=datas_list,
            mercado=mercado,
            setor=setor,
        )

        return {
            "nao_elegivel": False,
            "nome": nome,
            "score": analise["score"],
            "decisao": analise["decisao"],
            "sinal": sinal_from_score(analise["score"]),
            "contexto": contexto,
            "preco": float(preco_atual),
            "confiabilidade": "reduzida" if avisos else "alta",
            "avisos": avisos,
        }

    except Exception as e:
        return {"erro": str(e)}


async def persistir(conn, ticker: str, resultado: dict, mercado: str = "neutro"):
    """INSERT na tabela scores_historico, idempotente por (ticker, data_referencia)."""
    await conn.execute("""
        INSERT INTO ativos (ticker, nome, setor)
        VALUES ($1::varchar, $2, NULL)
        ON CONFLICT (ticker) DO UPDATE SET nome = EXCLUDED.nome
    """, ticker, resultado.get("nome", ticker))

    nao_elegivel = resultado.get("nao_elegivel", False)

    await conn.execute("""
        INSERT INTO scores_historico (
            ticker, data_referencia, score, decisao, sinal,
            mercado, contexto, preco,
            nao_elegivel, motivo_bloqueio, confiabilidade, avisos_confiabilidade
        ) VALUES ($1::varchar,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
        ON CONFLICT (ticker, data_referencia) DO UPDATE SET
            score = EXCLUDED.score,
            decisao = EXCLUDED.decisao,
            sinal = EXCLUDED.sinal,
            contexto = EXCLUDED.contexto,
            preco = EXCLUDED.preco,
            nao_elegivel = EXCLUDED.nao_elegivel,
            motivo_bloqueio = EXCLUDED.motivo_bloqueio,
            confiabilidade = EXCLUDED.confiabilidade,
            avisos_confiabilidade = EXCLUDED.avisos_confiabilidade,
            calculado_em = now()
    """,
        ticker,
        date.today(),
        float(resultado.get("score") or 0),
        resultado.get("decisao") or "evitar",
        resultado.get("sinal") or "Evitar",
        mercado,
        resultado.get("contexto"),
        resultado.get("preco"),
        nao_elegivel,
        resultado.get("motivo_bloqueio"),
        resultado.get("confiabilidade"),
        resultado.get("avisos") or [],
    )


def calcular_regime_mercado() -> str:
    try:
        ibov = yf.Ticker("^BVSP")
        ibov_hist = ibov.history(period="1y")
        if len(ibov_hist) >= 200:
            ibov_precos = ibov_hist["Close"].tolist()
            ibov_atual = ibov_precos[-1]
            ibov_mm50 = sum(ibov_precos[-50:]) / 50
            ibov_mm200 = sum(ibov_precos[-200:]) / 200
            if ibov_atual > ibov_mm50 and ibov_mm50 > ibov_mm200:
                return "bull"
            elif ibov_atual < ibov_mm50 and ibov_mm50 < ibov_mm200:
                return "bear"
        return "neutro"
    except Exception:
        return "neutro"


async def main():
    with open(TICKERS_FILE) as f:
        data = json.load(f)
    tickers = data["tickers"]
    total = len(tickers)

    print(f"=== Batch Zionix — {date.today()} ===")
    print(f"Total de tickers: {total}")
    print(f"Motor TS em: {NEXTJS_URL}/api/score")

    print("Calculando regime de mercado (IBOV)...")
    mercado = calcular_regime_mercado()
    print(f"Regime: {mercado}\n")

    conn = await asyncpg.connect(DB_URL, ssl="require")

    contadores = {"ok": 0, "bloqueado": 0, "reduzida": 0, "erro": 0}

    for i in range(0, total, BATCH_SIZE):
        lote = tickers[i : i + BATCH_SIZE]

        for ticker in lote:
            ticker_sa = f"{ticker}.SA"
            resultado = calcular_score_ativo(ticker_sa, mercado=mercado)

            if "erro" in resultado:
                contadores["erro"] += 1
                print(f"  {ticker}: ERRO — {resultado['erro']}")
                continue

            try:
                await persistir(conn, ticker, resultado, mercado)
            except Exception as e:
                contadores["erro"] += 1
                print(f"  {ticker}: ERRO DB — {e}")
                continue

            if resultado.get("nao_elegivel"):
                contadores["bloqueado"] += 1
                print(f"  {ticker}: bloqueado — {resultado.get('motivo_bloqueio')}")
            elif resultado.get("confiabilidade") == "reduzida":
                contadores["reduzida"] += 1
                print(f"  {ticker}: score={resultado['score']} confiabilidade=reduzida")
            else:
                contadores["ok"] += 1
                print(f"  {ticker}: score={resultado['score']} decisao={resultado['decisao']}")

        processados = min(i + BATCH_SIZE, total)
        print(f"--- {processados}/{total} processados ---\n")

        if i + BATCH_SIZE < total:
            time.sleep(SLEEP_ENTRE_BATCHES)

    print("Atualizando scores_atual...")
    await conn.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY scores_atual")
    await conn.close()

    print(f"\n=== RESULTADO FINAL ===")
    print(f"  OK (confiabilidade alta):    {contadores['ok']}")
    print(f"  Confiabilidade reduzida:     {contadores['reduzida']}")
    print(f"  Bloqueados (sem histórico):  {contadores['bloqueado']}")
    print(f"  Erros:                       {contadores['erro']}")
    print(f"  Total:                       {sum(contadores.values())}")


asyncio.run(main())
