import asyncio
from datetime import date

import asyncpg
from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
import yfinance as yf

from openai import OpenAI
import os
from dotenv import load_dotenv

load_dotenv()

_openai_client = None

def get_openai_client():
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _openai_client

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
        resposta = get_openai_client().responses.create(
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
        resposta = get_openai_client().responses.create(
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


@app.get("/health")
async def health():
    return {"status": "ok"}


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


@app.get("/analises")
async def analises():
    try:
        conn = await asyncpg.connect(_DB_URL, ssl="require")
        rows = await conn.fetch("""
            SELECT s.ticker, a.nome, a.setor, s.score, s.decisao, s.sinal,
                   s.mercado, s.contexto, s.confiabilidade
            FROM scores_atual s
            LEFT JOIN ativos a ON a.ticker = s.ticker
            WHERE s.nao_elegivel = false
        """)
        await conn.close()

        if not rows:
            return {"erro": "sem dados"}

        # regime de mercado dominante
        from collections import Counter
        mercado_counter = Counter(r["mercado"] for r in rows)
        mercado = mercado_counter.most_common(1)[0][0]

        # contagem por decisao
        por_decisao = dict(Counter(r["decisao"] for r in rows))

        # distribuição por faixas de score
        faixas = {"0-20": 0, "20-40": 0, "40-60": 0, "60-80": 0, "80-100": 0}
        for r in rows:
            s = float(r["score"])
            if s < 20:      faixas["0-20"] += 1
            elif s < 40:    faixas["20-40"] += 1
            elif s < 60:    faixas["40-60"] += 1
            elif s < 80:    faixas["60-80"] += 1
            else:           faixas["80-100"] += 1
        distribuicao = [{"faixa": k, "count": v} for k, v in faixas.items()]

        # agrupamento por setor
        setores: dict = {}
        for r in rows:
            setor = r["setor"] or "Outros"
            s = float(r["score"])
            if setor not in setores:
                setores[setor] = {"count": 0, "score_total": 0.0, "top_ticker": r["ticker"], "top_score": s}
            setores[setor]["count"] += 1
            setores[setor]["score_total"] += s
            if s > setores[setor]["top_score"]:
                setores[setor]["top_score"] = s
                setores[setor]["top_ticker"] = r["ticker"]
        por_setor = sorted(
            [{"setor": k, "count": v["count"],
              "score_medio": round(v["score_total"] / v["count"], 1),
              "top_ticker": v["top_ticker"]}
             for k, v in setores.items()],
            key=lambda x: x["score_medio"], reverse=True
        )

        # destaques: top momentum (tendencia_forte + pullback)
        momentum_rows = sorted(
            [r for r in rows if r["contexto"] in ("tendencia_forte", "pullback")],
            key=lambda r: float(r["score"]), reverse=True
        )[:3]
        top_momentum = [{"ticker": r["ticker"].replace(".SA", ""), "score": float(r["score"]),
                         "contexto": r["contexto"], "sinal": r["sinal"]} for r in momentum_rows]

        # destaques: top estrutural (confiabilidade alta, excluindo os do momentum)
        momentum_tickers = {r["ticker"] for r in momentum_rows}
        estrutural_rows = sorted(
            [r for r in rows if r["confiabilidade"] == "alta" and r["ticker"] not in momentum_tickers],
            key=lambda r: float(r["score"]), reverse=True
        )[:3]
        top_estrutural = [{"ticker": r["ticker"].replace(".SA", ""), "score": float(r["score"]),
                           "contexto": r["contexto"], "sinal": r["sinal"]} for r in estrutural_rows]

        # ativos agrupados por decisão, ordenados por score desc
        decisoes = ["comprar", "manter", "aguardar", "cautela", "evitar"]
        ativos_por_decisao = {d: [] for d in decisoes}
        for r in sorted(rows, key=lambda r: float(r["score"]), reverse=True):
            d = r["decisao"]
            if d in ativos_por_decisao:
                ativos_por_decisao[d].append({
                    "ticker": r["ticker"].replace(".SA", ""),
                    "nome": r["nome"],
                    "score": float(r["score"]),
                    "sinal": r["sinal"],
                })

        return {
            "mercado": mercado,
            "total_ativos": len(rows),
            "por_decisao": por_decisao,
            "distribuicao": distribuicao,
            "por_setor": por_setor,
            "destaques": {"top_momentum": top_momentum, "top_estrutural": top_estrutural},
            "ativos_por_decisao": ativos_por_decisao,
        }
    except Exception as e:
        return {"erro": str(e)}


@app.post("/api/analise-ia/{ticker}")
async def analise_ia(ticker: str, body: dict = Body(...)):
    """Gera leitura da IA explicando o score do ativo. Cache diário no Supabase."""
    ticker = ticker.upper()
    score = float(body.get("score", 0))
    decisao = body.get("decisao", "aguardar")
    sinal = body.get("sinal", "")
    mercado = body.get("mercado", "neutro")
    setor = body.get("setor", "") or "não informado"
    nome = body.get("nome", ticker)

    try:
        conn = await asyncpg.connect(_DB_URL, ssl="require")

        # Garante que a tabela existe (idempotente)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS leituras_ia (
                id SERIAL PRIMARY KEY,
                ticker VARCHAR NOT NULL,
                texto TEXT NOT NULL,
                score_no_momento NUMERIC,
                data_geracao DATE NOT NULL DEFAULT CURRENT_DATE,
                criado_em TIMESTAMPTZ DEFAULT now(),
                UNIQUE(ticker, data_geracao)
            )
        """)

        # Verifica cache do dia
        row = await conn.fetchrow(
            "SELECT texto FROM leituras_ia WHERE ticker = $1::varchar AND data_geracao = CURRENT_DATE",
            ticker
        )
        if row:
            await conn.close()
            return {"texto": row["texto"], "cache": True}

        # Monta contexto rico para o prompt
        decisao_label = {
            "comprar": "Compra — ativo com setup favorável",
            "manter": "Manter — tendência positiva, sem sinal de entrada nova",
            "aguardar": "Aguardar — sem setup claro no momento",
            "cautela": "Cautela — sinais mistos ou estrutura fraca",
            "evitar": "Evitar — estrutura técnica deteriorada",
        }.get(decisao, decisao)

        mercado_label = {
            "bull": "mercado em alta (IBOV acima das médias)",
            "bear": "mercado em queda (IBOV abaixo das médias)",
            "neutro": "mercado sem tendência definida",
        }.get(mercado, mercado)

        prompt = f"""Você é um analista de investimentos explicando para um investidor iniciante brasileiro por que uma ação recebeu determinada nota de análise técnica.

Dados do ativo:
- Empresa: {nome} ({ticker})
- Setor: {setor}
- Score técnico: {round(score)}/100
- Decisão do modelo: {decisao_label}
- Sinal operacional: {sinal}
- Contexto de mercado: {mercado_label}

Escreva exatamente 2 frases em português claro, sem jargão técnico:
1. Explique objetivamente por que o ativo recebeu esse score (o que está bem ou mal na análise técnica)
2. O que isso significa na prática para quem acompanha esse ativo hoje

Regras:
- Não mencione o número do score diretamente
- Não use palavras como "médias móveis", "RSI", "ATR", "drawdown", "volatilidade"
- Use linguagem simples: "o preço está subindo com consistência", "o ativo perdeu força", "há pressão compradora", etc.
- Seja específico para esse ativo — não escreva texto genérico
- Não faça previsões ("pode subir", "tende a cair")
- Máximo 60 palavras no total

Resposta:"""

        try:
            resposta = get_openai_client().responses.create(
                model="gpt-4o-mini",
                input=prompt
            )
            texto = limpar_texto_ia(resposta.output_text)
        except Exception as e:
            print(f"[analise-ia] erro IA: {e}")
            texto = f"{nome} apresenta {decisao_label.lower()} no cenário atual de {mercado_label}."

        # Salva no cache (ignora conflito se outro request simultâneo já salvou)
        try:
            await conn.execute(
                """INSERT INTO leituras_ia (ticker, texto, score_no_momento)
                   VALUES ($1::varchar, $2, $3)
                   ON CONFLICT (ticker, data_geracao) DO NOTHING""",
                ticker, texto, score
            )
        except Exception as e:
            print(f"[analise-ia] erro cache: {e}")

        await conn.close()
        return {"texto": texto, "cache": False}

    except Exception as e:
        return {"texto": f"Análise técnica indica {decisao} para {nome} no contexto atual.", "cache": False, "erro": str(e)}


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