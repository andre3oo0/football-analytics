"""Ingestion package: fetch football-data.org responses, cache them as raw
JSON, and upsert them into the DuckDB `raw` schema by natural key.

Ingestion is deliberately *thin*: it lands the untouched API payload keyed by
its natural key. All field-level interpretation (rename, cast, business logic)
happens downstream in dbt, not here.
"""
