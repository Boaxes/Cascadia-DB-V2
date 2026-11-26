-- Keep a point in step with the coordinates it is drawn from.
--
-- geom is derived: the columns are the truth and the point is a copy the map
-- reads. Anything that changes one has to change the other, and doing that in
-- application code means every write path has to remember -- which is exactly
-- what went wrong. Restoring an edit put the longitude back and left the point
-- where it was, so the record showed one position and reported another.
--
-- A trigger cannot forget. It also covers writes the application never sees:
-- a correction made in DBeaver or pgAdmin, or by the Access front ends after
-- they are relinked, keeps the map honest.
--
-- Only tables whose point comes from their own coordinate columns are covered.
-- TrackT.geom is built from a GPS file and DailyEffortT's positions are derived
-- from events and tracks, so neither belongs here.

CREATE OR REPLACE FUNCTION dbo.point_from(lat double precision, lon double precision)
RETURNS geometry(Point, 4326) LANGUAGE sql IMMUTABLE AS $$
    SELECT CASE
        -- (0,0) is a real place in the Gulf of Guinea and never where Cascadia
        -- works, so it means the position was not recorded.
        WHEN lat IS NULL OR lon IS NULL          THEN NULL
        WHEN lat = 0 AND lon = 0                 THEN NULL
        WHEN lon NOT BETWEEN -180 AND 180        THEN NULL
        WHEN lat NOT BETWEEN -90 AND 90          THEN NULL
        ELSE ST_SetSRID(ST_MakePoint(lon, lat), 4326)
    END
$$;

CREATE OR REPLACE FUNCTION dbo.sighting_geometry() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.geom     := dbo.point_from(NEW."Start Dec Lat", NEW."Start Dec Long");
    NEW.end_geom := dbo.point_from(NEW."End Dec Lat",   NEW."End Dec Long");
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION dbo.child_geometry() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.geom := dbo.point_from(NEW."Dec Lat", NEW."Dec Long");
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS sighting_geometry ON dbo."SightingT";
CREATE TRIGGER sighting_geometry BEFORE INSERT OR UPDATE ON dbo."SightingT"
    FOR EACH ROW EXECUTE FUNCTION dbo.sighting_geometry();

DROP TRIGGER IF EXISTS condition_geometry ON dbo."DailyConditionT";
CREATE TRIGGER condition_geometry BEFORE INSERT OR UPDATE ON dbo."DailyConditionT"
    FOR EACH ROW EXECUTE FUNCTION dbo.child_geometry();

DROP TRIGGER IF EXISTS event_geometry ON dbo."DailyEventT";
CREATE TRIGGER event_geometry BEFORE INSERT OR UPDATE ON dbo."DailyEventT"
    FOR EACH ROW EXECUTE FUNCTION dbo.child_geometry();
