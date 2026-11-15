-- Executed by the postgres image on first start (empty data volume) as POSTGRES_USER.
-- Integration tests run against this database so they never touch development data.
CREATE DATABASE tastify_test;
