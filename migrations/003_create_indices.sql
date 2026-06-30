-- histórico por ticker (gráfico de evolução do score)
CREATE INDEX idx_scores_historico_ticker_data
  ON scores_historico (ticker, data_referencia DESC);

-- auditoria: distribuição de confiabilidade por dia
CREATE INDEX idx_scores_historico_confiabilidade_data
  ON scores_historico (data_referencia, confiabilidade);
