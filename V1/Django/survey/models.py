"""
Models over the survey database.

Every model here reads an `app` view, not a table, and every one is
`managed = False` -- Django must never generate a migration that touches them.
The views are single-table and auto-updatable, so a write passes straight
through to the `dbo` table underneath; the schema is resolved by the
connection's search_path rather than named here, because Django would quote a
dotted db_table as one identifier.

Field names match the view's column names, so `db_column` appears only on
foreign keys, where Django would otherwise look for `<name>_id_id`.
"""

from django.contrib.gis.db import models

# A track implying a speed above this is not a real vessel track. Seven
# tracks have corrupted geometry producing lengths up to 56,060 nautical
# miles, and fourteen span months rather than a day. See
# docs/08-Data-That-Needs-Review.md.
IMPLAUSIBLE_SPEED_KN = 40


class Species(models.Model):
    id = models.BigAutoField(primary_key=True)
    code = models.TextField(unique=True)
    common_name = models.TextField(null=True)
    scientific_name = models.TextField(null=True)
    # cetacean | pinniped | other_marine | unidentified | non_animal
    category = models.TextField()

    class Meta:
        managed = False
        db_table = "species"
        ordering = ["common_name", "code"]

    def __str__(self):
        return self.common_name or self.code

    CATEGORY_LABELS = {
        "cetacean": "Cetacean", "pinniped": "Pinniped",
        "other_marine": "Other marine", "unidentified": "Unidentified",
        "non_animal": "Not an animal",
    }

    @property
    def category_label(self):
        return self.CATEGORY_LABELS.get(self.category, self.category)

    @property
    def name_is_authoritative(self):
        """False where no name is assigned. The template marks those."""
        return bool(self.common_name)


class Vessel(models.Model):
    id = models.BigAutoField(primary_key=True)
    legacy_vessel_id = models.IntegerField(null=True)
    code = models.TextField(unique=True)
    name = models.TextField()  # the literal 'Unknown' for 106 of 183

    class Meta:
        managed = False
        db_table = "vessel"
        ordering = ["name", "code"]

    def __str__(self):
        return self.label

    @property
    def label(self):
        """The code where no real name is recorded, so nothing shows 'Unknown'."""
        return self.code if self.name == "Unknown" else self.name


class DailyEffort(models.Model):
    id = models.BigAutoField(primary_key=True)
    legacy_daily_effort_id = models.IntegerField(unique=True)
    research_group = models.TextField(null=True)
    effort_date = models.DateField(null=True)
    start_time = models.TimeField(null=True)
    end_time = models.TimeField(null=True)
    vessel = models.ForeignKey(
        Vessel, models.DO_NOTHING, db_column="vessel_id", null=True,
        related_name="efforts",
    )
    locality = models.TextField(null=True)
    launch = models.TextField(null=True)
    return_location = models.TextField(null=True)
    survey_type = models.TextField(null=True)
    region = models.TextField(null=True)
    sub_area = models.TextField(null=True)
    project_objective = models.TextField(null=True)
    personnel = models.TextField(null=True)
    survey_comments = models.TextField(null=True)
    time_off_effort = models.DurationField(null=True)
    total_survey_effort = models.DurationField(null=True)
    distance_recorded_nm = models.DecimalField(max_digits=10, decimal_places=3, null=True)
    start_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    start_lon = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    start_point = models.PointField(srid=4326, null=True)
    # event | track | record | none
    start_coord_source = models.TextField()
    end_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    end_lon = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    end_point = models.PointField(srid=4326, null=True)
    # event | track | none
    end_coord_source = models.TextField()
    # Only for efforts with no GPS file. Never a substitute for track.geom.

    class Meta:
        managed = False
        db_table = "daily_effort"
        ordering = ["-effort_date", "-legacy_daily_effort_id"]

    def __str__(self):
        return f"Effort {self.legacy_daily_effort_id}"

    def get_absolute_url(self):
        return f"/efforts/{self.legacy_daily_effort_id}/"

    # Where the position came from decides how much it can be trusted. A B
    # event is the crew saying the effort began here. A record is the earliest
    # position of the day, which may be hours in.
    # Keyed by the values the rebuild writes (promote.build_effort_positions).
    # What the position came from, then what that is, shown as
    # Source: "B" Log Entry(Begin).
    START_SOURCES = {
        "event_B": ('"B" Log Entry', "Begin"),
        "gps_track": ("GPS Track", "Start"),
        "first_positioned_record": ("Earliest Position", "Not Departure"),
    }
    END_SOURCES = {
        "event_T": ('"T" Log Entry', "End"),
        "gps_track": ("GPS Track", "End"),
    }

    # An effort with no track at all and one whose file has gone missing are
    # different problems, so they never share a colour.
    @property
    def track_state(self):
        if self.track_count == 0:
            return ("problem-no_track", "No track file")
        if self.available_tracks:
            return ("pill-green", "Available")
        return ("problem-missing_file", "File missing")

    @property
    def position_is_departure_point(self):
        return self.start_coord_source in ("event", "track")

    @property
    def start_source(self):
        return self.START_SOURCES.get(self.start_coord_source, (self.start_coord_source, ""))

    @property
    def end_source(self):
        return self.END_SOURCES.get(self.end_coord_source, (self.end_coord_source, ""))

    @property
    def end_source_label(self):
        """The end source as plain text, for the map's popup."""
        name, detail = self.end_source
        return f"{name}({detail})" if detail else (name or "")


class Track(models.Model):
    id = models.BigAutoField(primary_key=True)
    legacy_track_id = models.IntegerField(null=True, unique=True)
    research_group = models.TextField(null=True)
    daily_effort = models.ForeignKey(
        DailyEffort, models.DO_NOTHING, db_column="daily_effort_id", null=True,
        related_name="tracks",
    )
    object_key = models.TextField(null=True)
    # available | missing_file | unassociated | unresolved
    track_status = models.TextField()
    vessel = models.ForeignKey(
        Vessel, models.DO_NOTHING, db_column="vessel_id", null=True,
        related_name="tracks",
    )
    track_source = models.TextField(null=True)
    track_complete_code = models.TextField(null=True)
    survey_date = models.DateField(null=True)
    useable = models.BooleanField()
    geom = models.MultiLineStringField(srid=4326, null=True)
    point_count = models.IntegerField(null=True)
    start_time_utc = models.DateTimeField(null=True)
    end_time_utc = models.DateTimeField(null=True)
    length_nm = models.DecimalField(max_digits=10, decimal_places=3, null=True)
    comments = models.TextField(null=True)

    class Meta:
        managed = False
        db_table = "track"
        ordering = ["-survey_date"]

    def __str__(self):
        return f"Track {self.legacy_track_id}"

    # The same names and colours as the admin Track files page. The stored
    # status is what the file was when last checked; what a record is shown
    # as is worked out from its link and its file, so a record linked by an
    # older tool without its status being updated still reads correctly.
    HAS_FILE = ("available", "unassociated")
    STATUS_LABELS = {
        "available": "Available",
        "missing_file": "File missing",
        "unlinked": "Unlinked file",
        "lost": "Lost file",
    }

    @property
    def state(self):
        has_file = self.track_status in self.HAS_FILE
        if self.daily_effort_id is not None:
            return "available" if has_file else "missing_file"
        return "unlinked" if has_file else "lost"

    @property
    def status_label(self):
        return self.STATUS_LABELS[self.state]

    @property
    def status_class(self):
        return "pill-green" if self.state == "available" else f"problem-{self.state}"

    @property
    def duration_hours(self):
        if not self.start_time_utc or not self.end_time_utc:
            return None
        seconds = (self.end_time_utc - self.start_time_utc).total_seconds()
        return seconds / 3600 if seconds > 0 else None

    @property
    def implied_speed_kn(self):
        """Average speed the recorded length and duration imply."""
        hours = self.duration_hours
        if hours is None or self.length_nm is None:
            return None
        return float(self.length_nm) / hours

    @property
    def length_is_plausible(self):
        """False where the geometry is corrupted or the track spans months.

        Anything derived from `length_nm` must check this first. Returning
        None means there is not enough information to judge, which the
        templates treat as unverified rather than as good.
        """
        if self.length_nm is None:
            return None
        speed = self.implied_speed_kn
        if speed is None:
            return None
        return speed <= IMPLAUSIBLE_SPEED_KN


class Sighting(models.Model):
    id = models.BigAutoField(primary_key=True)
    legacy_sighting_id = models.IntegerField(unique=True)
    research_group = models.TextField(null=True)
    daily_effort = models.ForeignKey(
        DailyEffort, models.DO_NOTHING, db_column="daily_effort_id", null=True,
        related_name="sightings",
    )
    sighting_number = models.TextField(null=True)
    vessel = models.ForeignKey(
        Vessel, models.DO_NOTHING, db_column="vessel_id", null=True,
        related_name="sightings",
    )
    species = models.ForeignKey(
        Species, models.DO_NOTHING, db_column="species_id", null=True,
        related_name="sightings",
    )
    species_uncertain = models.BooleanField()
    species_raw = models.TextField(null=True)
    sighting_date = models.DateField(null=True)
    sighting_time = models.TimeField(null=True)
    sighting_datetime = models.DateTimeField(null=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    lon = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    geom = models.PointField(srid=4326, null=True)
    end_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    end_lon = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    position_type = models.TextField(null=True)
    sight_type = models.TextField(null=True)
    est_size_best = models.IntegerField(null=True)
    est_size_min = models.IntegerField(null=True)
    est_size_max = models.IntegerField(null=True)
    num_calves = models.SmallIntegerField(null=True)
    group_behavior = models.TextField(null=True)
    group_type = models.TextField(null=True)
    depth_m = models.DecimalField(max_digits=7, decimal_places=1, null=True)
    photos_taken = models.BooleanField()
    comments = models.TextField(null=True)
    identified_individual_count = models.IntegerField()
    # Offered as optional columns on an export.
    bearing = models.IntegerField(null=True)
    range_m = models.IntegerField(null=True)
    reticle = models.FloatField(null=True)
    range_source = models.TextField(null=True)
    photo_series_1 = models.TextField(null=True)
    photo_frames_1 = models.TextField(null=True)
    photographer_1 = models.TextField(null=True)

    class Meta:
        managed = False
        db_table = "sighting"
        ordering = ["-sighting_date", "-legacy_sighting_id"]

    def __str__(self):
        return f"Sighting {self.legacy_sighting_id}"

    def get_absolute_url(self):
        return f"/sightings/{self.legacy_sighting_id}/"

    @property
    def group_estimate_is_consistent(self):
        """False for the 1,316 sightings whose best estimate sits outside
        their own minimum and maximum. All three are still displayed as
        recorded; the page just says they disagree.
        """
        if self.est_size_best is None:
            return None
        if self.est_size_min is not None and self.est_size_best < self.est_size_min:
            return False
        if self.est_size_max is not None and self.est_size_best > self.est_size_max:
            return False
        return True


class DailyCondition(models.Model):
    id = models.BigAutoField(primary_key=True)
    legacy_daily_condition_id = models.IntegerField(unique=True)
    research_group = models.TextField(null=True)
    daily_effort = models.ForeignKey(
        DailyEffort, models.DO_NOTHING, db_column="daily_effort_id", null=True,
        related_name="conditions",
    )
    condition_datetime = models.DateTimeField(null=True)
    condition_time = models.TimeField(null=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    lon = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    geom = models.PointField(srid=4326, null=True)
    beaufort = models.SmallIntegerField(null=True)
    swell_ft = models.SmallIntegerField(null=True)
    cloud_cover_pct = models.SmallIntegerField(null=True)
    precipitation = models.TextField(null=True)
    quality = models.TextField(null=True)
    visibility_nm = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    comments = models.TextField(null=True)

    class Meta:
        managed = False
        db_table = "daily_condition"
        ordering = ["condition_datetime", "condition_time"]


class DailyEvent(models.Model):
    id = models.BigAutoField(primary_key=True)
    legacy_daily_event_id = models.IntegerField(unique=True)
    research_group = models.TextField(null=True)
    daily_effort = models.ForeignKey(
        DailyEffort, models.DO_NOTHING, db_column="daily_effort_id", null=True,
        related_name="events",
    )
    code = models.TextField(null=True)
    event_datetime = models.DateTimeField(null=True)
    event_time = models.TimeField(null=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    lon = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    geom = models.PointField(srid=4326, null=True)
    observer_left = models.TextField(null=True)
    observer_right = models.TextField(null=True)
    recorder = models.TextField(null=True)
    comments = models.TextField(null=True)

    class Meta:
        managed = False
        db_table = "daily_event"
        ordering = ["event_datetime", "event_time"]


class Sample(models.Model):
    id = models.BigAutoField(primary_key=True)
    legacy_sample_id = models.IntegerField(unique=True)
    research_group = models.TextField(null=True)
    sighting = models.ForeignKey(
        Sighting, models.DO_NOTHING, db_column="sighting_id", null=True,
        related_name="samples",
    )
    species = models.ForeignKey(
        Species, models.DO_NOTHING, db_column="species_id", null=True,
        related_name="samples",
    )
    sample_number = models.TextField(null=True)
    sample_type = models.TextField(null=True)
    sample_datetime = models.DateTimeField(null=True)
    certainty_of_id = models.TextField(null=True)
    preservation = models.TextField(null=True)
    sampled_by = models.TextField(null=True)
    field_id = models.TextField(null=True)
    reaction = models.TextField(null=True)
    comments = models.TextField(null=True)

    class Meta:
        managed = False
        db_table = "sample"
        ordering = ["sample_datetime", "sample_number"]


class EffortTimeline(models.Model):
    """The effort_timeline view: weather readings, log entries and sightings.

    One row per thing that happened during an effort, in time order. The view
    is in the schema so anybody querying SEDB gets it too, not only this page.
    """

    # Synthetic, because the three branches of the union share no key space.
    # V1 used a plain integer here and Django treated it as a primary key,
    # which it was not: an event and a sighting could collide on it.
    row_key = models.TextField(primary_key=True)
    daily_effort = models.ForeignKey(
        DailyEffort, models.DO_NOTHING, db_column="daily_effort_id", null=True,
        related_name="timeline",
    )
    kind = models.TextField()  # condition | event | sighting
    at = models.DateTimeField(null=True)
    legacy_id = models.IntegerField(null=True)
    lat = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    lon = models.DecimalField(max_digits=9, decimal_places=6, null=True)
    geom = models.PointField(srid=4326, null=True)
    label = models.TextField(null=True)

    class Meta:
        managed = False
        db_table = "effort_timeline"
        ordering = ["at", "row_key"]

    KIND_LABELS = {
        "condition": "Weather reading",
        "event": "Log entry",
        "sighting": "Sighting",
    }

    @property
    def kind_label(self):
        return self.KIND_LABELS.get(self.kind, self.kind)

    @property
    def url(self):
        """Sightings have a page of their own. The other two do not."""
        return f"/sightings/{self.legacy_id}/" if self.kind == "sighting" else None
