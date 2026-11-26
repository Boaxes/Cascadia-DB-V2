{#
  A model goes in the schema its folder names -- dbo or app -- plus the
  build's suffix, `_next` by default: every build writes beside the live
  schemas, and `dbt run-operation swap` moves the result into place. dbt's
  default would have been <target schema>_<name>.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}{{ var('schema_suffix', '_next') }}
    {%- endif -%}
{%- endmacro %}
