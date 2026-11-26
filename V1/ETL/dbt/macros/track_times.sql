{#
  A track's StartTime and EndTime.

  DB167 keeps them in Pacific local time (America/Los_Angeles, with daylight
  saving), unlike the track files, which are UTC. dbo and app keep UTC, so the
  build converts what DB167 holds (models/dbo/TrackT.sql) with
  app.track_time_utc(). A value the website wrote is already UTC and is not
  converted: it is replayed on top of the converted value.

  Twice a year a Pacific time is not one moment. In spring the hour from 02:00
  to 03:00 does not exist; Postgres reads such a time as the hour after it.
  In autumn the hour from 01:00 to 02:00 happens twice, an hour apart, and a
  time in it could be either. The file's own first (for StartTime) or last
  (for EndTime) point time, kept in app.track_geometry, settles it when it
  falls in one of the two hours; otherwise the standard-time (second) reading
  is used.
#}
{% macro track_time_functions() %}
    create or replace function app.track_time_utc(local_time timestamp, file_time timestamp default null)
    returns timestamp language sql stable as $fn$
        select case
            when local_time is null then null
            when (((local_time + interval '7 hours') at time zone 'UTC') at time zone 'America/Los_Angeles') = local_time
             and (((local_time + interval '8 hours') at time zone 'UTC') at time zone 'America/Los_Angeles') = local_time then
                -- The repeated hour: the daylight reading is 7 hours ahead of UTC, the standard one 8.
                case when file_time >= date_trunc('hour', local_time) + interval '7 hours'
                      and file_time <  date_trunc('hour', local_time) + interval '8 hours'
                     then local_time + interval '7 hours'
                     else local_time + interval '8 hours' end
            else (local_time at time zone 'America/Los_Angeles') at time zone 'UTC'
        end
    $fn$;

    -- The other way, for the checks of what DB167 holds: a UTC time as Pacific local time.
    create or replace function app.track_time_pacific(utc_time timestamp)
    returns timestamp language sql immutable as $fn$
        select (utc_time at time zone 'UTC') at time zone 'America/Los_Angeles'
    $fn$;
{% endmacro %}


{# The first or last time of a DB167 track's file, in UTC, from app.track_geometry, for a row of c0. #}
{% macro geometry_time(column) %}
    {{- "(select min(g." ~ column ~ ") from " ~ source('app', 'track_geometry') ~ " g where lower(g.object_key) = lower(c0.\"TrackFileName\"))" -}}
{% endmacro %}
