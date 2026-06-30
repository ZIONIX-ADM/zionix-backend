CREATE MATERIALIZED VIEW scores_atual AS
SELECT DISTINCT ON (ticker) *
FROM scores_historico
ORDER BY ticker, data_referencia DESC;

CREATE UNIQUE INDEX idx_scores_atual_ticker ON scores_atual (ticker);

-- ranking: top N por score, só ativos elegíveis
CREATE INDEX idx_scores_atual_ranking
  ON scores_atual (score DESC)
  WHERE nao_elegivel = false;

-- consultas por decisão (ex: listar todos "comprar" hoje)
CREATE INDEX idx_scores_atual_decisao
  ON scores_atual (decisao)
  WHERE nao_elegivel = false;
