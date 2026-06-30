import asyncio
from datetime import date

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf

from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_DB_URL = os.getenv("DATABASE_URL", "").replace("postgresql+asyncpg://", "postgresql://")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

cache_ia_leitura = {}
cache_exposicao_risco = {}
contador_ia = 0


def limpar_texto_ia(texto):
    return (
        texto.replace("*", "")
        .replace("EXPOSIÇÃO:", "")
        .replace("RISCOS:", "")
        .strip()
    )


def calcular_drawdown_maximo(precos):
    topo = precos[0]
    max_dd = 0
    for preco in precos:
        if preco > topo:
            topo = preco
        dd = (topo - preco) / topo * 100 if topo else 0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def verificar_historico(historico):
    if len(historico) < 252:
        return f"histórico insuficiente ({len(historico)} candles, mínimo 252)"
    return None


def verificar_confiabilidade(historico, preco_atual):
    avisos = []
    precos = historico["Close"].tolist()

    vol_financeiro = (historico["Volume"] * historico["Close"]).mean()
    if vol_financeiro < 5_000_000:
        avisos.append(f"volume médio diário baixo (R$ {vol_financeiro:,.0f}/dia)")

    retornos = historico["Close"].pct_change().dropna()
    vol_diaria = retornos.std() * 100
    if vol_diaria > 3.5:
        avisos.append(f"volatilidade diária elevada ({vol_diaria:.2f}%)")

    drawdown = calcular_drawdown_maximo(precos)
    if drawdown > 70:
        avisos.append(f"drawdown histórico elevado ({drawdown:.1f}%)")

    if preco_atual < 3.0:
        avisos.append(f"preço abaixo de R$ 3,00 (R$ {preco_atual:.2f})")

    return avisos


def traduzir_setor(setor):
    traducoes = {
        "Energy": "Energia",
        "Basic Materials": "Materiais Básicos",
        "Financial Services": "Serviços Financeiros",
        "Technology": "Tecnologia",
        "Healthcare": "Saúde",
        "Consumer Cyclical": "Consumo Cíclico",
        "Consumer Defensive": "Consumo Não Cíclico",
        "Industrials": "Indústria",
        "Real Estate": "Imobiliário",
        "Communication Services": "Comunicação",
        "Utilities": "Utilidades Públicas",
    }

    return traducoes.get(
        setor,
        setor if setor else "Não informado"
    )


def gerar_exposicao_riscos_ia(nome, setor):
    global contador_ia

    chave = f"{nome}-{setor}"

    if chave in cache_exposicao_risco:
        return cache_exposicao_risco[chave]

    if contador_ia >= 20:
        return (
            f"{nome} está exposta ao setor de {setor.lower()} e às condições do mercado.",
            "Os principais riscos envolvem mudanças no setor e no ambiente econômico."
        )

    contador_ia += 1

    prompt = f"""
Você é um analista financeiro.

Empresa: {nome}
Setor: {setor}

Explique como se estivesse conversando com um investidor comum:

1) A exposição da empresa: o que mais influencia seu desempenho.
2) Os principais riscos do negócio.

Regras:
- Seja direto, natural e fácil de entender
- Não use linguagem acadêmica
- Não use markdown, asteriscos ou títulos decorados
- Seja específico para o setor
- Não invente dados específicos da empresa
- Não use frases genéricas como "volatilidade do mercado" sozinha
- Máximo 2 frases para exposição
- Máximo 2 frases para riscos

Formato obrigatório:

EXPOSIÇÃO:
...

RISCOS:
...
"""

    try:
        resposta = client.responses.create(
            model="gpt-4o-mini",
            input=prompt
        )

        texto = resposta.output_text
        partes = texto.split("RISCOS:")

        exposicao = limpar_texto_ia(partes[0])
        riscos = (
            limpar_texto_ia(partes[1])
            if len(partes) > 1
            else "Riscos não identificados."
        )

        cache_exposicao_risco[chave] = (exposicao, riscos)

        return exposicao, riscos

    except Exception as e:
        print("Erro IA risco:", e)

        return (
            f"{nome} está exposta ao setor de {setor.lower()}.",
            "Os principais riscos envolvem mudanças no setor e no ambiente econômico."
        )


def gerar_interpretacao_ia(
    nome,
    cenario,
    volatilidade,
    distancia_media,
    posicao,
    forca,
    pressao
):
    global contador_ia

    chave = f"{nome}-{cenario}-{volatilidade}-{distancia_media}-{posicao}-{forca}-{pressao}"

    if chave in cache_ia_leitura:
        return cache_ia_leitura[chave]

    if contador_ia >= 20:
        return f"O ativo está em cenário de {cenario} com volatilidade {volatilidade}."

    contador_ia += 1

    prompt = f"""
Você é um analista profissional do mercado financeiro.

Analise o comportamento do ativo:

Empresa: {nome}
Cenário atual: {cenario}
Volatilidade: {volatilidade}
Distância da média: {distancia_media:.2f}%
Posição do preço: {posicao}
Força do movimento: {forca}
Pressão atual: {pressao}

Objetivo:
Explicar de forma clara o que está acontecendo com o ativo no curto prazo.

Regras:
- Escreva entre 2 e 3 frases
- Seja claro e direto
- Não use jargões técnicos
- Não invente causas externas
- Interprete apenas o comportamento do preço
- Não mostre números
- Traduza os dados em significado prático
- Explique o impacto: perda de força, continuidade, correção ou pressão
- Evite termos como "range", "sequência" e "média" na resposta
- Sempre traduza para linguagem simples do dia a dia
- Não faça previsões como "pode subir" ou "pode recuperar"
- Cada frase deve trazer uma informação nova
- Evite apenas descrever o movimento
- Foque no significado do comportamento
- Destaque se o movimento parece forte, fraco ou esticado
- Traga uma leitura que ajude na tomada de decisão

Resposta:
"""

    try:
        resposta = client.responses.create(
            model="gpt-4o-mini",
            input=prompt
        )

        texto = limpar_texto_ia(resposta.output_text)
        cache_ia_leitura[chave] = texto

        return texto

    except Exception as e:
        print("Erro IA leitura:", e)

        return f"O ativo está em cenário de {cenario}."


def analisar_ativo(
    tendencia,
    variacao_percentual,
    posicao_range,
    sequencia,
    volatilidade,
    setor
):
    # 🔥 FORÇA
    if sequencia >= 4:
        forca = "forte"
    elif sequencia >= 2:
        forca = "moderada"
    else:
        forca = "fraca"

    # 📍 POSIÇÃO
    if posicao_range > 0.7:
        posicao = "próximo das máximas"
    elif posicao_range < 0.3:
        posicao = "próximo das mínimas"
    else:
        posicao = "em região intermediária"

    # ⚡ PRESSÃO
    if variacao_percentual > 0:
        pressao = "compradora"
    elif variacao_percentual < 0:
        pressao = "vendedora"
    else:
        pressao = "neutra"

    # 🌎 CENÁRIO
    if tendencia == "alta" and variacao_percentual < 0:
        cenario = "correção dentro de tendência de alta"
    elif tendencia == "alta":
        cenario = "alta consistente"
    elif tendencia == "queda" and variacao_percentual < 0:
        cenario = "queda consistente"
    elif tendencia == "queda":
        cenario = "possível estabilização"
    else:
        cenario = "movimento lateral"

    # 🧠 SCORE CENTRAL
    score = 50

    if tendencia == "alta":
        score += 15
    else:
        score -= 15

    if posicao_range < 0.3:
        score += 20
    elif posicao_range > 0.7:
        score -= 10

    if sequencia >= 3:
        score += 10

    if volatilidade == "alta":
        score -= 10

    setor_lower = setor.lower()

    if (
        "energia" in setor_lower
        or "financeiro" in setor_lower
    ):
        score += 5

    if (
        "varejo" in setor_lower
        or "consumo" in setor_lower
    ):
        score -= 5

    score = max(0, min(100, score))

    # 🎯 RECOMENDAÇÃO
    if score >= 70:
        sinal = "Compra forte"
    elif score >= 55:
        sinal = "Compra"
    elif score >= 45:
        sinal = "Aguardar confirmação"
    elif score >= 30:
        sinal = "Cautela"
    else:
        sinal = "Evitar"

    # decisao compatível com os thresholds de gerarDiagnosticoDiario
    if score >= 68:
        decisao = "comprar"
    elif score >= 52:
        decisao = "manter"
    elif score >= 42:
        decisao = "aguardar"
    elif score >= 30:
        decisao = "cautela"
    else:
        decisao = "evitar"

    # contexto aproximado derivado dos dados disponíveis no Python
    if tendencia == "alta" and sequencia >= 3:
        contexto = "tendencia_forte"
    elif tendencia == "alta":
        contexto = "pullback"
    elif tendencia == "queda":
        contexto = "bearish"
    else:
        contexto = "neutro"

    return {
        "score": score,
        "cenario": cenario,
        "sinal": sinal,
        "forca": forca,
        "pressao": pressao,
        "posicao": posicao,
        "decisao": decisao,
        "contexto": contexto,
    }


async def salvar_score(
    ticker, score, decisao, sinal, mercado, contexto, preco,
    confiabilidade, avisos, nao_elegivel=False, motivo_bloqueio=None
):
    try:
        conn = await asyncpg.connect(_DB_URL, ssl="require")
        await conn.execute("""
            INSERT INTO ativos (ticker, nome, setor)
            VALUES ($1::varchar, $1::varchar, NULL)
            ON CONFLICT (ticker) DO NOTHING
        """, ticker)
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
                mercado = EXCLUDED.mercado,
                contexto = EXCLUDED.contexto,
                preco = EXCLUDED.preco,
                confiabilidade = EXCLUDED.confiabilidade,
                avisos_confiabilidade = EXCLUDED.avisos_confiabilidade,
                calculado_em = now()
        """, ticker, date.today(), float(score), decisao, sinal,
            mercado, contexto, float(preco) if preco else None,
            nao_elegivel, motivo_bloqueio, confiabilidade, avisos or [])
        await conn.close()
    except Exception as e:
        print(f"[salvar_score] erro silencioso: {e}")


@app.get("/buscar/{ticker}")
async def buscar_ativo(ticker: str):
    try:
        ticker = ticker.upper()

        if not ticker.endswith(".SA"):
            ticker += ".SA"

        empresa = yf.Ticker(ticker)
        info = empresa.info

        nome = info.get("longName") or ticker
        setor = traduzir_setor(info.get("sector"))

        preco_raw = info.get("currentPrice")

        if preco_raw:
            preco_formatado = (
                f"R$ {preco_raw:,.2f}"
                .replace(",", "X")
                .replace(".", ",")
                .replace("X", ".")
            )
        else:
            preco_formatado = "-"

        moeda = info.get("currency") or "BRL"

        exposicao, riscos = gerar_exposicao_riscos_ia(
            nome,
            setor
        )

        try:
            ibov = yf.Ticker("^BVSP")
            ibov_hist = ibov.history(period="1y")
            if len(ibov_hist) >= 200:
                ibov_precos = ibov_hist["Close"].tolist()
                ibov_atual = ibov_precos[-1]
                ibov_mm50 = sum(ibov_precos[-50:]) / 50
                ibov_mm200 = sum(ibov_precos[-200:]) / 200
                if ibov_atual > ibov_mm50 and ibov_mm50 > ibov_mm200:
                    mercado = "bull"
                elif ibov_atual < ibov_mm50 and ibov_mm50 < ibov_mm200:
                    mercado = "bear"
                else:
                    mercado = "neutro"
            else:
                mercado = "neutro"
        except Exception:
            mercado = "neutro"

        historico = empresa.history(period="2y")

        if historico.empty:
            return {"erro": "Sem dados"}

        preco_atual_raw = historico["Close"].iloc[-1]

        motivo_bloqueio = verificar_historico(historico)
        if motivo_bloqueio:
            return {
                "nao_elegivel": True,
                "motivo": motivo_bloqueio,
                "ticker": ticker,
                "nome": nome
            }

        avisos = verificar_confiabilidade(historico, preco_atual_raw)

        # usa apenas o último ano para o gráfico e score
        historico = historico.tail(252)

        datas = []
        precos = []
        highs = []
        lows = []

        for index, row in historico.iterrows():
            datas.append(index.strftime("%d/%m"))
            precos.append(round(row["Close"], 2))
            highs.append(round(row["High"], 2))
            lows.append(round(row["Low"], 2))

        preco_atual = historico["Close"].iloc[-1]
        preco_anterior = (
            historico["Close"].iloc[-2]
            if len(historico) >= 2
            else preco_atual
        )

        variacao = preco_atual - preco_anterior

        variacao_percentual = (
            (variacao / preco_anterior) * 100
            if preco_anterior != 0
            else 0
        )

        preco_inicio = historico["Close"].iloc[0]

        tendencia = (
            "alta"
            if preco_atual > preco_inicio
            else "queda"
        )

        variacoes = historico["Close"].pct_change().dropna()
        vol = variacoes.std() if not variacoes.empty else 0

        if vol > 0.03:
            volatilidade = "alta"
        elif vol > 0.015:
            volatilidade = "moderada"
        else:
            volatilidade = "baixa"

        media_20 = historico["Close"].tail(20).mean()

        distancia_media = (
            ((preco_atual - media_20) / media_20) * 100
            if media_20
            else 0
        )

        maximo = historico["High"].max()
        minimo = historico["Low"].min()

        posicao_range = (
            (preco_atual - minimo) / (maximo - minimo)
            if (maximo - minimo) != 0
            else 0
        )

        sequencia = 0

        for i in range(len(historico) - 1, 0, -1):
            if historico["Close"].iloc[i] > historico["Close"].iloc[i - 1]:
                sequencia += 1
            else:
                break

        analise = analisar_ativo(
            tendencia=tendencia,
            variacao_percentual=variacao_percentual,
            posicao_range=posicao_range,
            sequencia=sequencia,
            volatilidade=volatilidade,
            setor=setor
        )

        cenario = analise["cenario"]
        sinal = analise["sinal"]
        forca = analise["forca"]
        pressao = analise["pressao"]
        posicao = analise["posicao"]
        score = analise["score"]
        decisao = analise["decisao"]
        contexto_analise = analise["contexto"]

        asyncio.create_task(salvar_score(
            ticker, score, decisao, sinal, mercado, contexto_analise,
            preco_atual, confiabilidade="reduzida" if avisos else "alta",
            avisos=avisos
        ))

        interpretacao = gerar_interpretacao_ia(
            nome,
            cenario,
            volatilidade,
            distancia_media,
            posicao,
            forca,
            pressao
        )

        return {
            "ticker": ticker,
            "nome": nome,
            "setor": setor,
            "preco": preco_formatado,
            "moeda": moeda,

            "score": score,
            "cenario": cenario,
            "sinal": sinal,
            "forca": forca,
            "pressao": pressao,
            "posicao": posicao,

            "exposicao": exposicao,
            "riscos": riscos,

            "variacao": round(variacao, 2),
            "variacao_percentual": round(variacao_percentual, 2),

            "mercado": mercado,
            "confiabilidade": "reduzida" if avisos else "alta",
            "avisos_confiabilidade": avisos,

            "grafico": {
                "datas": datas,
                "precos": precos,
                "highs": highs,
                "lows": lows
            },

            "interpretacao_grafico": interpretacao
        }

    except Exception as e:
        return {
            "erro": "Erro ao buscar dados",
            "detalhe": str(e)
        }


@app.get("/ranking")
async def ranking(limite: int = 10):
    try:
        conn = await asyncpg.connect(_DB_URL, ssl="require")
        rows = await conn.fetch("""
            SELECT s.ticker, a.nome, s.score, s.decisao, s.sinal, s.mercado,
                   s.contexto, s.preco, s.confiabilidade, s.data_referencia
            FROM scores_atual s
            LEFT JOIN ativos a ON a.ticker = s.ticker
            WHERE s.nao_elegivel = false
              AND s.confiabilidade = 'alta'
            ORDER BY s.score DESC
            LIMIT $1
        """, limite)
        await conn.close()

        return [
            {
                "ticker": r["ticker"],
                "nome": r["nome"],
                "score": float(r["score"]),
                "decisao": r["decisao"],
                "sinal": r["sinal"],
                "mercado": r["mercado"],
                "preco": float(r["preco"]) if r["preco"] else None,
                "data_referencia": str(r["data_referencia"]),
            }
            for r in rows
        ]
    except Exception as e:
        return {"erro": str(e)}


@app.get("/historico/{ticker}")
def historico(
    ticker: str,
    inicio: str,
    fim: str
):
    try:
        ticker = ticker.upper()

        if not ticker.endswith(".SA"):
            ticker += ".SA"

        ativo = yf.Ticker(ticker)

        hist = ativo.history(
            start=inicio,
            end=fim
        )

        if hist.empty:
            return {"erro": "Sem dados"}

        dados = []

        for index, row in hist.iterrows():
            dados.append({
                "data": index.strftime("%Y-%m-%d"),
                "preco": round(row["Close"], 2),
                "open": round(row["Open"], 2),
                "high": round(row["High"], 2),
                "low": round(row["Low"], 2),
                "close": round(row["Close"], 2),
            })

        return {
            "ticker": ticker,
            "periodo": "custom",
            "dados": dados
        }

    except Exception as e:
        return {
            "erro": "Erro ao buscar histórico",
            "detalhe": str(e)
        }