CREATE TABLE scores_historico (
    id                      BIGSERIAL PRIMARY KEY,
    ticker                  VARCHAR(10) NOT NULL REFERENCES ativos(ticker),
    data_referencia         DATE NOT NULL,
    calculado_em            TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- saída do gerarDiagnosticoDiario
    score                   NUMERIC(5,2) NOT NULL,
    decisao                 VARCHAR(10) NOT NULL,
    sinal                   TEXT,  -- output de gerarRecomendacao(score)

    -- mercado/contexto no momento do cálculo
    mercado                 VARCHAR(10),
    contexto                VARCHAR(20),
    preco                   NUMERIC(12,2),

    -- elegibilidade (resultado do snapshot)
    nao_elegivel            BOOLEAN NOT NULL DEFAULT false,
    motivo_bloqueio         TEXT,
    confiabilidade          VARCHAR(10),
    avisos_confiabilidade   TEXT[],

    UNIQUE (ticker, data_referencia)
);
