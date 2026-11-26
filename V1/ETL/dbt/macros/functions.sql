{#
  The functions dbo's triggers call when the website edits a position, and
  that the build uses to turn coordinates into map points.
#}
{% macro dbo_functions(schema) %}
CREATE OR REPLACE FUNCTION {{ schema }}.point_from(lat double precision, lon double precision)
RETURNS geometry(Point, 4326) LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        -- (0, 0) means the position was not recorded.
        WHEN lat IS NULL OR lon IS NULL          THEN NULL
        WHEN lat = 0 AND lon = 0                 THEN NULL
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


{#
  The functions the build itself uses.

  key_text(value)  one part of a combination, as the hash reads it: text
                   trimmed, runs of spaces made one, and in lower case, so 'Zip'
                   and 'ZIP ' are the same vessel; empty text is NULL.
  key_hash(parts)  a combination hashed into one whole number: the first 63
                   bits of the MD5 of its parts, so always positive. The same
                   parts always give the same number.
  title_distance   how many letters a spelling is from Title Case, as the
                   spelling rule measures it (models/build/spelling_map.sql).
  unit_distance    how many capitals a unit of measure has (m, ft, nm).
#}
{% macro build_functions(schema) %}
CREATE OR REPLACE FUNCTION {{ schema }}.key_text(value text) RETURNS text
LANGUAGE sql IMMUTABLE AS $$
    SELECT nullif(lower(regexp_replace(btrim(value, E' \t\r\n\f\v '), '\s+', ' ', 'g')), '')
$$;

CREATE OR REPLACE FUNCTION {{ schema }}.key_hash(parts text[]) RETURNS bigint
LANGUAGE sql IMMUTABLE AS $$
    SELECT (('x' || left(md5(array_to_string(
                array(SELECT coalesce(p, E'\\N') FROM unnest(parts) WITH ORDINALITY u(p, i) ORDER BY i),
                chr(31))), 16))::bit(64)::bigint) & 9223372036854775807
$$;

CREATE OR REPLACE FUNCTION {{ schema }}.title_distance(s text) RETURNS integer
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE
    word    text;
    letters text;
    pos     integer := 0;
    total   integer := 0;
    n       integer;
    title   integer;
    caps    integer;
    low     integer;
    minor   text[] := ARRAY['a', 'an', 'and', 'at', 'by', 'de', 'del', 'for', 'from', 'in', 'la', 'of', 'on',
                            'or', 'the', 'to', 'van', 'von', 'with'];
BEGIN
    FOR word IN SELECT m[1] FROM regexp_matches(s, '([A-Za-z'']+)', 'g') WITH ORDINALITY r(m, i) ORDER BY i LOOP
        pos := pos + 1;
        -- McKinley, MacRae, O'Brien are Title Case; Mckinley is McKinley written wrongly.
        CONTINUE WHEN word ~ '^(Mc|Mac|O'')[A-Z][a-z]+$';
        IF word ~ '^Mc[a-z]+$' THEN
            total := total + 1;
            CONTINUE;
        END IF;
        letters := regexp_replace(word, '[^A-Za-z]', '', 'g');
        n := length(letters);
        -- Letters to change for Title Case: the first a capital, the rest not.
        title := 0;
        FOR j IN 1 .. n LOOP
            IF (substr(letters, j, 1) ~ '[A-Z]') <> (j = 1) THEN
                title := title + 1;
            END IF;
        END LOOP;
        -- All capitals is an abbreviation (CRC, SBE) only in a word of up to 4 letters.
        caps := CASE WHEN n <= 4 THEN length(regexp_replace(letters, '[A-Z]', '', 'g')) ELSE title END;
        -- Short joining words may be lower case after the first word.
        low := CASE WHEN pos > 1 AND lower(word) = ANY (minor)
                    THEN length(regexp_replace(letters, '[^A-Z]', '', 'g')) ELSE title END;
        total := total + least(title, caps, low);
    END LOOP;
    RETURN total;
END;
$$;

CREATE OR REPLACE FUNCTION {{ schema }}.unit_distance(s text) RETURNS integer
LANGUAGE sql IMMUTABLE AS $$
    SELECT length(regexp_replace(s, '[^[:upper:]]', '', 'g'))
$$;
{% endmacro %}


{# The schema the build's own functions are in, quoted: "build_next" during a build. #}
{% macro build_fn() -%}
    {{ adapter.quote('build' ~ var('schema_suffix', '_next')) }}
{%- endmacro %}
