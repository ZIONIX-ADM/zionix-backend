CREATE TABLE ativos (
    ticker          VARCHAR(10) PRIMARY KEY,
    nome            TEXT NOT NULL,
    setor           TEXT,
    ativo           BOOLEAN NOT NULL DEFAULT true,
    criado_em       TIMESTAMPTZ NOT NULL DEFAULT now(),
    atualizado_em   TIMESTAMPTZ NOT NULL DEFAULT now()
);
