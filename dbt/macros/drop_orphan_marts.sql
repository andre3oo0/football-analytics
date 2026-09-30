{#
  Drop tables and views in the marts schema that no model builds any more: a
  renamed model's old table, or a __dbt_backup left by an interrupted run. The
  warehouse is carried from night to night, so without this they would sit in
  it forever. Runs as an on-run-end hook (see dbt_project.yml).
#}
{% macro drop_orphan_marts() %}
  {% if execute %}
    {% set expected = [] %}
    {% for node in graph.nodes.values() %}
      {% if node.resource_type in ('model', 'seed', 'snapshot') and node.schema == 'marts' %}
        {% do expected.append(node.alias | lower) %}
      {% endif %}
    {% endfor %}

    {% set existing = run_query(
        "select table_name, table_type from information_schema.tables "
        ~ "where table_catalog = '" ~ target.database ~ "' and table_schema = 'marts'"
    ) %}
    {% for row in existing %}
      {% if row[0] | lower not in expected %}
        {% do log("Dropping marts." ~ row[0] ~ ": no model builds it any more", info=true) %}
        {% do run_query(
            "drop " ~ ("view" if row[1] == "VIEW" else "table")
            ~ " if exists " ~ target.database ~ ".marts." ~ row[0]
        ) %}
      {% endif %}
    {% endfor %}
  {% endif %}
{% endmacro %}
