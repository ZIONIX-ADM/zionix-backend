import json
import math
import ssl
import time
import urllib.request
import yfinance as yf

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

B3_API = "https://sistemaswebb3-listados.b3.com.br/listedCompaniesProxy/CompanyCall/GetInitialCompanies/"

# segmentos e tipos que indicam BDR, ETF, FII ou instrumento não-ação
EXCLUIR_TIPOS = {"4", "5", "6", "7"}  # 4=DRE(BDR), 5=ETF, 6=FII, 7=outros
EXCLUIR_SEGMENTOS = {"BDR", "ETF", "FII", "Fundo"}


def pagina_token(numero: int, tamanho: int = 120) -> str:
    import base64
    payload = json.dumps({
        "language": "pt-br",
        "pageNumber": numero,
        "pageSize": tamanho
    })
    return base64.b64encode(payload.encode()).decode()


def buscar_todas_empresas() -> list[dict]:
    empresas = []
    pagina = 1
    total_paginas = None

    while True:
        token = pagina_token(pagina)
        url = B3_API + token
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15, context=_ssl_ctx) as r:
            data = json.loads(r.read())

        if total_paginas is None:
            total = data["page"]["totalRecords"]
            total_paginas = math.ceil(total / 120)
            print(f"Total de empresas na B3: {total} ({total_paginas} páginas)")

        empresas.extend(data["results"])
        print(f"  página {pagina}/{total_paginas} — {len(empresas)} empresas coletadas")

        if pagina >= total_paginas:
            break
        pagina += 1
        time.sleep(0.3)

    return empresas


def filtrar_acoes(empresas: list[dict]) -> list[str]:
    codigos_base = set()
    for e in empresas:
        tipo = e.get("type", "")
        segmento = e.get("segment", "") or ""
        status = e.get("status", "")
        tipo_bdr = e.get("typeBDR", "") or ""
        codigo = (e.get("issuingCompany") or "").strip().upper()

        if status != "A":
            continue
        if tipo in EXCLUIR_TIPOS:
            continue
        if any(ex.lower() in segmento.lower() for ex in EXCLUIR_SEGMENTOS):
            continue
        if tipo_bdr:
            continue
        if not codigo or len(codigo) > 4:
            continue

        codigos_base.add(codigo)

    # gera tickers candidatos: ON (3), PN (4), Units (11)
    candidatos = []
    for codigo in sorted(codigos_base):
        candidatos.append(f"{codigo}3")
        candidatos.append(f"{codigo}4")
        candidatos.append(f"{codigo}11")

    return candidatos


def validar_tickers(candidatos: list[str], batch: int = 30) -> list[dict]:
    validos = []
    total = len(candidatos)
    print(f"\nValidando {total} tickers candidatos via yfinance (batches de {batch})...")

    for i in range(0, total, batch):
        lote = candidatos[i:i + batch]
        tickers_sa = [f"{t}.SA" for t in lote]

        try:
            dados = yf.download(
                tickers_sa,
                period="5d",
                auto_adjust=True,
                progress=False,
                threads=True
            )

            for t, tsa in zip(lote, tickers_sa):
                try:
                    if "Close" in dados.columns.get_level_values(0):
                        serie = dados["Close"][tsa].dropna()
                    else:
                        serie = dados["Close"].dropna() if len(lote) == 1 else None

                    if serie is not None and len(serie) >= 3:
                        validos.append({"ticker": t, "ticker_sa": tsa})
                except Exception:
                    pass

        except Exception as e:
            print(f"  erro no batch {i//batch + 1}: {e}")

        print(f"  {min(i + batch, total)}/{total} verificados — {len(validos)} válidos até agora")
        time.sleep(1)

    return validos


if __name__ == "__main__":
    print("=== Coletando empresas listadas na B3 ===")
    empresas = buscar_todas_empresas()

    print(f"\n=== Filtrando ações (excluindo BDRs, ETFs, FIIs) ===")
    candidatos = filtrar_acoes(empresas)
    print(f"Candidatos gerados: {len(candidatos)}")

    print(f"\n=== Validando existência via yfinance ===")
    validos = validar_tickers(candidatos)

    resultado = {
        "total": len(validos),
        "tickers": [v["ticker"] for v in validos]
    }

    with open("tickers_b3.json", "w") as f:
        json.dump(resultado, f, indent=2)

    print(f"\n=== RESULTADO ===")
    print(f"Tickers válidos: {len(validos)}")
    print(f"Amostra (10 primeiros): {[v['ticker'] for v in validos[:10]]}")
    print(f"Arquivo salvo: tickers_b3.json")
