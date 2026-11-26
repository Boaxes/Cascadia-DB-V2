{#
  A view the website writes through. dbt's own view materialization cannot add
  WITH CHECK OPTION, which stops a write through the view creating a row the
  view could not see (a non-CRC record, say).

      {{ config(materialized='updatable_view', meta={'check_option': true}) }}

  Every build writes into a fresh schema (macros/build_schemas.sql), so the
  view never exists beforehand and there is nothing to replace.
#}
{% materialization updatable_view, adapter='postgres' %}
    {%- set target_relation = this.incorporate(type='view') -%}
    {{ run_hooks(pre_hooks) }}
    {% call statement('main') -%}
        create view {{ target_relation }} as
        {{ sql }}
        {% if (config.get('meta') or {}).get('check_option') %}with check option{% endif %}
    {%- endcall %}
    {{ run_hooks(post_hooks) }}
    {{ adapter.commit() }}
    {{ return({'relations': [target_relation]}) }}
{% endmaterialization %}
