{#
  Model-level grain test: no two rows share the same values across `columns`.
  (The same idea as dbt_utils.unique_combination_of_columns, kept local so the
  project has no package dependency.)
#}
{% test unique_combination(model, columns) %}

select {{ columns | join(', ') }}, count(*) as n_rows
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1

{% endtest %}
