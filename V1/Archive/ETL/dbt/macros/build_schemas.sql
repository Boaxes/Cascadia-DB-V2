{#
  Every build starts from empty schemas: dbo_next and app_next are dropped and
  created again, so nothing from an earlier or a failed build is left in them,
  and no name the new build gives an index or a constraint can clash with an
  old one. `run-operation swap` then moves them into place, and they are gone
  again: between builds the database has three schemas, raw, dbo and app.

  The build also writes on dbo_next the newest audit log entry it will replay
  (the watermark: macros/replay.sql, audit_watermark), so every model replays
  the same log and the swap can tell whether it has moved on since.

  Only `dbt build` and `dbt run` do this. `dbt test` and the rest leave the
  schemas alone.
#}
{% macro prepare_next_schemas() %}
    {% if execute and flags.WHICH in ('build', 'run') %}
        {% set suffix = var('schema_suffix', '_next') %}
        {% if suffix == '' %}
            {{ exceptions.raise_compiler_error("schema_suffix is empty: a build would drop the live schemas.") }}
        {% endif %}
        {% for name in ['dbo', 'app'] %}
            {#- Through the adapter, not plain SQL, so dbt's own record of what
                exists is kept right: it lists the relations before this runs. -#}
            {% set schema = api.Relation.create(database=target.database, schema=name ~ suffix) %}
            {% do adapter.drop_schema(schema) %}
            {% do adapter.create_schema(schema) %}
        {% endfor %}
        {% do run_query(dbo_functions('"dbo' ~ suffix ~ '"')) %}
        {% set newest = run_query('select coalesce(max(id), 0) from app.audit_log').columns[0].values()[0] %}
        {% do run_query('comment on schema "dbo' ~ suffix ~ '" is \'Built from app.audit_log up to entry ' ~ newest ~ '.\'') %}
    {% endif %}
{% endmacro %}


{#
  The functions the geometry triggers call, and that the build itself uses to
  turn coordinates into points. From ETL/schema/dbo_geometry.sql, except that
  point_from() treats a lone 0 as not recorded too (R7).
#}
{% macro dbo_functions(schema) %}
CREATE OR REPLACE FUNCTION {{ schema }}.point_from(lat double precision, lon double precision)
RETURNS geometry(Point, 4326) LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        -- Nobody surveys on the equator or the Greenwich meridian, so a 0 means
        -- the position was not recorded (R7).
        WHEN lat IS NULL OR lon IS NULL          THEN NULL
        WHEN lat = 0 OR lon = 0                  THEN NULL
        WHEN lon NOT BETWEEN -180 AND 180        THEN NULL
        WHEN lat NOT BETWEEN -90 AND 90          THEN NULL
        ELSE ST_SetSRID(ST_MakePoint(lon, lat), 4326)
    END
$$;

CREATE OR REPLACE FUNCTION {{ schema }}.sighting_geometry() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.geom     := dbo.point_from(NEW."Start Dec Lat", NEW."Start Dec Long");
    NEW.end_geom := dbo.point_from(NEW."End Dec Lat",   NEW."End Dec Long");
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION {{ schema }}.child_geometry() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.geom := dbo.point_from(NEW."Dec Lat", NEW."Dec Long");
    RETURN NEW;
END;
$$;
{% endmacro %}
