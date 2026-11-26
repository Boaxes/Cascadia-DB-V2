"""The Export Tool's writers with no database: every format opens, dates and
time zones come out as chosen, and a large export is written as it is read.

The sheets here are made by hand. What the database puts in them is tested
against the real data in TESTS/test_export.py.
"""

import datetime
import io
import json
import os
import sqlite3
import struct
import tempfile
import tracemalloc
import xml.etree.ElementTree as ET
import zipfile
from decimal import Decimal

from django.test import SimpleTestCase

from survey import exporters
from survey.exporters import OutSheet, Zone, point_wkb

try:
    import pyogrio
except ImportError:   # an image built before pyogrio joined requirements-dev.txt
    pyogrio = None

D, T, DT = datetime.date(2024, 7, 1), datetime.time(7, 30, 5), datetime.datetime(2024, 7, 1, 7, 30, 5)


def line_wkb(*lines):
    """A MultiLineString as PostGIS writes it with ST_AsBinary."""
    out = struct.pack("<BII", 1, exporters.MULTILINESTRING, len(lines))
    for line in lines:
        out += struct.pack("<BII", 1, exporters.LINESTRING, len(line))
        out += b"".join(struct.pack("<dd", x, y) for x, y in line)
    return out


def efforts(rows=None, geometry="line"):
    """An Efforts sheet of two rows, one with a track and one without."""
    if rows is None:
        rows = [
            ([26194, D, T, "Santa Barbara Channel", Decimal("12.500"), True, "MUS"],
             line_wkb([(-119.7, 34.4), (-119.8, 34.5)], [(-120.0, 34.6), (-120.1, 34.7)]), {"name": "Effort 26194"}),
            ([26195, None, None, None, None, None, None], None, {"name": "Effort 26195"}),
        ]
    return OutSheet("Efforts", "efforts",
                    ["Effort ID", "Date", "Start Time", "Locality", "Distance (nm)", "Track Length Suspect", "Vessel Code"],
                    ["int", "date", "time", "text", "float", "bool", "text"], iter(rows), geometry,
                    [False, False, False, False, False, True, True])


def sightings():
    return OutSheet("Sightings", "sightings", ["Sighting ID", "Date And Time", "Common Name"],
                    ["int", "datetime", "text"],
                    iter([([9377, DT, "Humpback Whale"], point_wkb(-119.5, 34.0),
                           {"name": "Humpback Whale 9377", "time": DT})]), "point")


def samples():
    return OutSheet("Samples", "samples", ["Sighting ID", "Sample Number"], ["int", "text"],
                    iter([([9377, "CRC-1"], None, {})]))


def write(fmt, sheets, **options):
    out = tempfile.TemporaryFile()
    exporters.write_export(fmt, sheets, out, **options)
    out.seek(0)
    return out


class ValueTests(SimpleTestCase):

    def test_empty_means_empty(self):
        for kind in ("text", "int", "date", "time", "datetime", "bool"):
            self.assertEqual(exporters.format_value(None, kind), "")
        # None, NA and NULL must never reach a file, where R would read them as data.
        self.assertNotIn("None", exporters.format_value(None, "text"))

    def test_the_two_date_formats(self):
        self.assertEqual(exporters.format_value(DT, "datetime", "iso"), "2024-07-01 07:30:05")
        self.assertEqual(exporters.format_value(DT, "datetime", "excel"), "7/1/2024 07:30:05")
        self.assertEqual(exporters.format_value(D, "date", "iso"), "2024-07-01")
        self.assertEqual(exporters.format_value(D, "date", "excel"), "7/1/2024")
        self.assertEqual(exporters.format_value(T, "time", "excel"), "07:30:05")

    def test_numbers_and_booleans(self):
        self.assertEqual(exporters.format_value(Decimal("12.500"), "float"), "12.5")
        self.assertEqual(exporters.format_value(Decimal("1000"), "float"), "1000")
        self.assertEqual(exporters.format_value(True, "bool"), "TRUE")
        self.assertEqual(exporters.format_value(False, "bool"), "FALSE")
        self.assertEqual(exporters.format_value("a\x00b\x1fc", "text"), "abc")

    def test_a_sheet_title_becomes_a_file_name(self):
        self.assertEqual(exporters.file_name("Sighting Events"), "sighting_events")
        self.assertEqual(exporters.file_name("Other Species"), "other_species")


class ZoneTests(SimpleTestCase):

    def test_recorded_times_are_pacific_and_move_to_utc(self):
        # In July Pacific is seven hours behind UTC, in January eight.
        utc, pacific = Zone("UTC"), Zone("Pacific")
        summer, winter = datetime.datetime(2024, 7, 1, 7, 30), datetime.datetime(2024, 1, 12, 8, 57)
        self.assertEqual(utc.record(summer), datetime.datetime(2024, 7, 1, 14, 30))
        self.assertEqual(utc.record(winter), datetime.datetime(2024, 1, 12, 16, 57))
        self.assertEqual(pacific.record(summer), summer)

    def test_a_date_and_a_time_in_two_columns_move_together(self):
        day, clock = Zone("UTC").record_date_time(datetime.date(2024, 7, 1), datetime.time(18, 0))
        self.assertEqual((day, clock), (datetime.date(2024, 7, 2), datetime.time(1, 0)))
        self.assertEqual(Zone("Pacific").record_date_time(datetime.date(2024, 7, 1), datetime.time(18, 0)),
                         (datetime.date(2024, 7, 1), datetime.time(18, 0)))

    def test_a_value_with_no_time_is_left_alone(self):
        zone = Zone("UTC")
        self.assertEqual(zone.record(datetime.datetime(2024, 4, 1)), datetime.datetime(2024, 4, 1))
        self.assertEqual(zone.record_date_time(D, None), (D, None))
        self.assertEqual(zone.record_date_time(None, T), (None, T))
        self.assertIsNone(zone.record(None))

    def test_an_unknown_zone_is_utc(self):
        self.assertEqual(Zone("Mars").name, "UTC")


class PositionTests(SimpleTestCase):

    def test_points_and_lines_read_back(self):
        self.assertEqual(exporters.wkb_geometry(point_wkb(-119.5, 34.0)),
                         {"type": "Point", "coordinates": [-119.5, 34.0]})
        geometry = exporters.wkb_geometry(line_wkb([(-1.0, 2.0), (-3.0, 4.0)], [(5.0, 6.0), (7.0, 8.0)]))
        self.assertEqual(geometry["type"], "MultiLineString")
        self.assertEqual(geometry["coordinates"], [[[-1.0, 2.0], [-3.0, 4.0]], [[5.0, 6.0], [7.0, 8.0]]])

    def test_bounds(self):
        self.assertEqual(exporters.wkb_bounds(point_wkb(-119.5, 34.0)), (-119.5, 34.0, -119.5, 34.0))
        self.assertEqual(exporters.wkb_bounds(line_wkb([(-1.0, 2.0), (-3.0, 4.0)], [(5.0, 6.0), (7.0, 8.0)])),
                         (-3.0, 2.0, 7.0, 8.0))

    def test_an_unsupported_geometry_is_refused(self):
        with self.assertRaises(ValueError):
            exporters.wkb_geometry(struct.pack("<BIdd", 1, 3, 0.0, 0.0))


class ExcelTests(SimpleTestCase):

    def book(self, sheets, **options):
        from openpyxl import load_workbook
        return load_workbook(write("xlsx", sheets, **options))

    def test_one_workbook_with_one_sheet_for_each_sheet_given(self):
        book = self.book([efforts(), sightings(), samples()])
        self.assertEqual(book.sheetnames, ["Efforts", "Sightings", "Samples"])
        sheet = book["Efforts"]
        self.assertEqual([c.value for c in sheet[1]][:3], ["Effort ID", "Date", "Start Time"])
        self.assertEqual(sheet.freeze_panes, "A2")
        self.assertEqual(sheet.max_row, 3)

    def test_numbers_dates_and_empties_stay_native(self):
        row = [c.value for c in self.book([efforts()])["Efforts"][2]]
        self.assertEqual(row, [26194, datetime.datetime(2024, 7, 1), datetime.time(7, 30, 5),
                               "Santa Barbara Channel", 12.5, True, "MUS"])
        empty = [c.value for c in self.book([efforts()])["Efforts"][3]]
        self.assertEqual(empty, [26195, None, None, None, None, None, None])

    def test_the_date_format_is_the_cells_number_format(self):
        iso = self.book([sightings()])["Sightings"]["B2"]
        excel = self.book([sightings()], date_format="excel")["Sightings"]["B2"]
        self.assertEqual(iso.number_format, "yyyy-mm-dd hh:mm:ss")
        self.assertEqual(excel.number_format, "m/d/yyyy h:mm:ss")

    def test_text_that_starts_with_an_equals_sign_is_not_a_formula(self):
        sheet = OutSheet("Notes", "notes", ["Comment"], ["text"], iter([(["=1+1"], None, {})]))
        cell = self.book([sheet])["Notes"]["A2"]
        self.assertEqual((cell.value, cell.data_type), ("=1+1", "s"))

    def test_a_sheet_longer_than_excel_can_hold_carries_on(self):
        rows = ((([n], None, {}) for n in range(1, 11)))
        long = OutSheet("Other Species", "other_species", ["Number"], ["int"], rows)
        book = self.book([long], max_rows=5)   # a heading and four rows to a sheet
        self.assertEqual(book.sheetnames, ["Other Species", "Other Species 2", "Other Species 3"])
        numbers = [c.value for name in book.sheetnames for (c,) in book[name].iter_rows(min_row=2)]
        self.assertEqual(numbers, list(range(1, 11)))
        self.assertEqual([book[n]["A1"].value for n in book.sheetnames], ["Number"] * 3)

    def test_an_empty_sheet_still_has_its_headings(self):
        empty = OutSheet("Tags", "tags", ["Sighting ID"], ["int"], iter([]))
        self.assertEqual([c.value for c in self.book([empty])["Tags"][1]], ["Sighting ID"])


class CsvTests(SimpleTestCase):

    def archive(self, sheets, **options):
        return zipfile.ZipFile(write("csv", sheets, **options))

    def test_a_zip_with_one_file_for_each_sheet(self):
        z = self.archive([efforts(), sightings(), samples()])
        self.assertEqual(sorted(z.namelist()), ["efforts.csv", "samples.csv", "sightings.csv"])

    def test_headings_values_and_a_byte_order_mark(self):
        raw = self.archive([efforts()]).read("efforts.csv")
        self.assertTrue(raw.startswith(b"\xef\xbb\xbf"))
        lines = raw.decode("utf-8-sig").splitlines()
        self.assertEqual(lines[0], "Effort ID,Date,Start Time,Locality,Distance (nm),Track Length Suspect,Vessel Code")
        self.assertEqual(lines[1], "26194,2024-07-01,07:30:05,Santa Barbara Channel,12.5,TRUE,MUS")
        self.assertEqual(lines[2], "26195,,,,,,")

    def test_excel_friendly_dates(self):
        text = self.archive([efforts()], date_format="excel").read("efforts.csv").decode("utf-8-sig")
        self.assertIn("26194,7/1/2024,07:30:05,", text)

    def test_commas_and_quotes_are_quoted(self):
        sheet = OutSheet("Notes", "notes", ["Comment"], ["text"], iter([(['a "b", c'], None, {})]))
        self.assertIn('"a ""b"", c"', self.archive([sheet]).read("notes.csv").decode("utf-8-sig"))


class GeoJsonTests(SimpleTestCase):

    def test_only_sheets_with_positions_are_written(self):
        z = zipfile.ZipFile(write("geojson", [efforts(), sightings(), samples()]))
        self.assertEqual(sorted(z.namelist()), ["efforts.geojson", "sightings.geojson"])

    def test_the_files_parse_and_carry_geometry_and_properties(self):
        z = zipfile.ZipFile(write("geojson", [efforts(), sightings()]))
        efforts_json = json.loads(z.read("efforts.geojson"))
        self.assertEqual(efforts_json["type"], "FeatureCollection")
        first, second = efforts_json["features"]
        self.assertEqual(first["geometry"]["type"], "MultiLineString")
        self.assertEqual(first["properties"]["Effort ID"], 26194)
        self.assertEqual(first["properties"]["Distance (nm)"], 12.5)
        self.assertEqual(first["properties"]["Date"], "2024-07-01")
        self.assertIs(first["properties"]["Track Length Suspect"], True)
        # No position: the row is still there, with a null geometry, so the counts match.
        self.assertIsNone(second["geometry"])
        self.assertIsNone(second["properties"]["Date"])
        point = json.loads(z.read("sightings.geojson"))["features"][0]
        self.assertEqual(point["geometry"], {"type": "Point", "coordinates": [-119.5, 34.0]})
        self.assertEqual(point["properties"]["Date And Time"], "2024-07-01 07:30:05")

    def test_an_empty_sheet_is_still_a_collection(self):
        empty = OutSheet("Efforts", "efforts", ["Effort ID"], ["int"], iter([]), "line")
        z = zipfile.ZipFile(write("geojson", [empty]))
        self.assertEqual(json.loads(z.read("efforts.geojson"))["features"], [])


class GpxTests(SimpleTestCase):

    NS = {"g": "http://www.topografix.com/GPX/1/1"}

    def test_sightings_are_waypoints_and_efforts_are_tracks(self):
        root = ET.parse(write("gpx", [efforts(), sightings(), samples()])).getroot()
        waypoints = root.findall("g:wpt", self.NS)
        tracks = root.findall("g:trk", self.NS)
        self.assertEqual(len(waypoints), 1)
        self.assertEqual(waypoints[0].get("lat"), "34.0000000")
        self.assertEqual(waypoints[0].find("g:time", self.NS).text, "2024-07-01T07:30:05Z")
        self.assertEqual(waypoints[0].find("g:name", self.NS).text, "Humpback Whale 9377")
        # The Effort with no track is left out, and the other has a segment for each line.
        self.assertEqual(len(tracks), 1)
        self.assertEqual(len(tracks[0].findall("g:trkseg", self.NS)), 2)
        points = tracks[0].findall("g:trkseg/g:trkpt", self.NS)
        self.assertEqual([(p.get("lat"), p.get("lon")) for p in points][0], ("34.4000000", "-119.7000000"))
        self.assertIn("Locality: Santa Barbara Channel", tracks[0].find("g:desc", self.NS).text)

    def test_waypoints_come_before_tracks_as_the_schema_requires(self):
        root = ET.parse(write("gpx", [efforts(), sightings()])).getroot()
        tags = [child.tag.split("}")[1] for child in root]
        self.assertEqual(tags, ["metadata", "wpt", "trk"])

    def test_special_characters_are_escaped(self):
        sheet = OutSheet("Sightings", "sightings", ["Comment"], ["text"],
                         iter([(["<b> & \"c\""], point_wkb(-1.0, 2.0), {"name": "A & B"})]), "point")
        root = ET.parse(write("gpx", [sheet])).getroot()
        self.assertEqual(root.find("g:wpt/g:name", self.NS).text, "A & B")
        self.assertIn("<b> & \"c\"", root.find("g:wpt/g:desc", self.NS).text)


class GeoPackageTests(SimpleTestCase):

    def path(self, sheets, **options):
        out = write("gpkg", sheets, **options)
        handle = tempfile.NamedTemporaryFile(suffix=".gpkg", delete=False)
        handle.write(out.read())
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def test_it_is_a_geopackage_with_a_layer_for_each_sheet_with_positions(self):
        db = sqlite3.connect(self.path([efforts(), sightings(), samples()]))
        self.addCleanup(db.close)
        self.assertEqual(db.execute("PRAGMA application_id").fetchone()[0], 0x47504B47)
        layers = dict(db.execute("SELECT table_name, data_type FROM gpkg_contents"))
        self.assertEqual(layers, {"efforts": "features", "sightings": "features"})
        self.assertEqual(dict(db.execute("SELECT table_name, geometry_type_name FROM gpkg_geometry_columns")),
                         {"efforts": "MULTILINESTRING", "sightings": "POINT"})
        self.assertEqual(db.execute("SELECT srs_id FROM gpkg_contents WHERE table_name = 'sightings'").fetchone()[0], 4326)
        self.assertIn(4326, [r[0] for r in db.execute("SELECT srs_id FROM gpkg_spatial_ref_sys")])

    def test_values_and_the_geometry_header(self):
        db = sqlite3.connect(self.path([efforts(), sightings()], utc=True))
        self.addCleanup(db.close)
        row = db.execute('SELECT geom, "Effort ID", "Date", "Distance (nm)", "Track Length Suspect" FROM efforts '
                         "ORDER BY fid").fetchone()
        self.assertEqual(row[0][:8], b"GP\x00\x01" + struct.pack("<i", 4326))
        self.assertEqual(row[1:], (26194, "2024-07-01", 12.5, 1))
        self.assertIsNone(db.execute("SELECT geom FROM efforts WHERE fid = 2").fetchone()[0])
        self.assertEqual(db.execute('SELECT "Date And Time" FROM sightings').fetchone()[0], "2024-07-01T07:30:05Z")
        bounds = db.execute("SELECT min_x, min_y, max_x, max_y FROM gpkg_contents WHERE table_name = 'efforts'").fetchone()
        self.assertEqual(bounds, (-120.1, 34.4, -119.7, 34.7))

    def test_a_time_in_pacific_is_not_marked_as_utc(self):
        db = sqlite3.connect(self.path([sightings()], utc=False))
        self.addCleanup(db.close)
        self.assertEqual(db.execute('SELECT "Date And Time" FROM sightings').fetchone()[0], "2024-07-01T07:30:05")

    def test_the_file_opens_in_gdal(self):
        if pyogrio is None:
            self.skipTest("pyogrio is not installed")
        path = self.path([efforts(), sightings()])
        layers = {name: kind for name, kind in pyogrio.list_layers(path)}
        self.assertEqual(set(layers), {"efforts", "sightings"})
        self.assertEqual(layers["efforts"], "MultiLineString")
        self.assertEqual(layers["sightings"], "Point")
        info = pyogrio.read_info(path, layer="efforts")
        self.assertEqual(info["features"], 2)
        self.assertEqual(info["crs"], "EPSG:4326")
        self.assertIn("Effort ID", info["fields"])
        _meta, _fids, geometry, fields = pyogrio.raw.read(path, layer="sightings")
        self.assertEqual(len(geometry), 1)
        self.assertEqual(list(fields[0]), [9377])


class RawFilesTests(SimpleTestCase):

    def files(self):
        yield "tracks/20240701-ROB.csv", b"datetime_utc,latitude,longitude\n"
        yield "tracks/20240702-ROB.csv", b"datetime_utc,latitude,longitude\n"
        yield "track_file_list.csv", "Effort ID,Track File,In The Tracks Folder\n"

    def test_any_format_becomes_a_zip_with_a_tracks_folder(self):
        for fmt, name in (("xlsx", "cascadia_export.xlsx"), ("csv", "efforts.csv"),
                          ("geojson", "efforts.geojson"), ("gpx", "cascadia_export.gpx"),
                          ("gpkg", "cascadia_export.gpkg")):
            with self.subTest(fmt=fmt):
                z = zipfile.ZipFile(write(fmt, [efforts(), sightings()], track_files=self.files()))
                names = z.namelist()
                self.assertIn(name, names)
                self.assertEqual([n for n in names if n.startswith("tracks/")],
                                 ["tracks/20240701-ROB.csv", "tracks/20240702-ROB.csv"])
                self.assertIn("track_file_list.csv", names)

    def test_the_data_file_inside_the_zip_is_the_real_thing(self):
        z = zipfile.ZipFile(write("xlsx", [efforts()], track_files=self.files()))
        from openpyxl import load_workbook
        self.assertEqual(load_workbook(io.BytesIO(z.read("cascadia_export.xlsx"))).sheetnames, ["Efforts"])

    def test_no_files_is_no_zip_for_a_single_file_format(self):
        self.assertFalse(zipfile.is_zipfile(write("gpx", [efforts()])))
        self.assertFalse(zipfile.is_zipfile(write("gpkg", [efforts()])))

    def test_an_unknown_format_is_refused(self):
        with self.assertRaises(ValueError):
            exporters.write_export("pdf", [efforts()], io.BytesIO())


class CompressionTests(SimpleTestCase):
    """The export's own files are compressed already, so the site's gzip
    middleware leaves them alone and still compresses everything else."""

    def respond(self, flagged):
        from django.http import HttpResponse, StreamingHttpResponse
        from django.test import RequestFactory
        from survey.middleware import GZipExceptDownloads

        def view(request):
            response = HttpResponse(b"x" * 5000) if not flagged else StreamingHttpResponse(iter([b"x" * 5000]))
            response.no_gzip = flagged
            return response

        request = RequestFactory().get("/", HTTP_ACCEPT_ENCODING="gzip")
        return GZipExceptDownloads(view)(request)

    def test_a_marked_response_is_not_compressed_again(self):
        response = self.respond(flagged=True)
        self.assertFalse(response.has_header("Content-Encoding"))
        self.assertEqual(b"".join(response.streaming_content), b"x" * 5000)

    def test_everything_else_still_is(self):
        self.assertEqual(self.respond(flagged=False)["Content-Encoding"], "gzip")


class LargeExportTests(SimpleTestCase):
    """A sheet of a million rows must not be held in memory. Each writer is
    given a generator and measured twice, on a sheet and on one ten times as
    long. If the writer kept the rows, the peak would grow with them."""

    SMALL, LARGE = 2_000, 20_000

    def big(self, rows):
        def made():
            for n in range(rows):
                yield ([n, DT, "Humpback Whale", Decimal("12.5"), "A comment of some length " * 2],
                       point_wkb(-119.5, 34.0), {"name": "Humpback Whale"})
        return OutSheet("Sightings", "sightings", ["ID", "When", "Species", "Distance", "Comment"],
                        ["int", "datetime", "text", "float", "text"], made(), "point")

    def peak(self, fmt, rows):
        tracemalloc.start()
        try:
            out = tempfile.TemporaryFile()
            exporters.write_export(fmt, [self.big(rows)], out)
            return tracemalloc.get_traced_memory()[1], out.tell()
        finally:
            tracemalloc.stop()

    def test_no_writer_holds_the_rows(self):
        for fmt in ("csv", "geojson", "gpkg", "xlsx", "gpx"):
            with self.subTest(fmt=fmt):
                self.peak(fmt, 10)   # the first use of a library is not what is being measured
                small, _ = self.peak(fmt, self.SMALL)
                large, size = self.peak(fmt, self.LARGE)
                self.assertGreater(size, 20_000)
                # Holding the large sheet would cost about 10 MB more than the small one.
                self.assertLess(large - small, 1024 * 1024,
                                f"{fmt} peaked at {small / 1e6:.1f} MB, then {large / 1e6:.1f} MB for ten times the rows")

    def test_the_rows_are_taken_one_at_a_time(self):
        taken = []

        def rows():
            for n in range(100_000):
                taken.append(n)
                yield [n], None, {}

        class Watch(io.RawIOBase):
            """Notes how many rows had been taken at each write."""
            def __init__(self):
                self.seen = []
            def writable(self):
                return True
            def write(self, data):
                self.seen.append(len(taken))
                return len(data)

        out = Watch()
        exporters.write_export("csv", [OutSheet("N", "n", ["N"], ["int"], rows())], out)
        # Output was written while rows were still to come, not all at the end.
        self.assertTrue(any(seen < 100_000 for seen in out.seen))
