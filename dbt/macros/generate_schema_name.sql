{#
  Use the custom schema name VERBATIM (staging / intermediate / marts) instead
  of dbt's default `<target_schema>_<custom_schema>` concatenation.

  The default concatenation exists to stop developers clobbering each other in a
  shared cloud warehouse. This project is a single local DuckDB file with one
  developer, so that safeguard is irrelevant and the concatenated names
  (`main_staging`, ...) only make the lineage DAG harder to read. Clean schema
  names it is.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
