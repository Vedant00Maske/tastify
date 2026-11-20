-- Runs once, on first start with an empty volume (docker-compose.prod.yml).
-- Query statistics for performance work (DEPLOYMENT.md, "Database").
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
