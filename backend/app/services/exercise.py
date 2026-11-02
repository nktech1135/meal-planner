"""Exercise: Compendium MET look-ups, energy estimates and activity-file parsing.

Energy added to a day's target is *net* exercise energy: what the workout burned above resting, since the
profile's energy estimate (Mifflin-St Jeor × activity factor) already counts resting energy for every hour
of the day. With 1 MET ≈ 1 kcal/kg/h (the Compendium's definition), net = (MET − 1) × weight × hours, and a
device-reported total has 1 × weight × hours taken off.
"""

import gzip
import io
import json
import math
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path

import defusedxml.ElementTree as SafeET
import fitdecode
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BodyMeasurement, Exercise, User

COMPENDIUM_FILE = Path(__file__).resolve().parent.parent / "data" / "compendium" / "adult_2024.json"
COMPENDIUM_CITATION = ("2024 Adult Compendium of Physical Activities (Herrmann SD et al., J Sport Health Sci "
                       "2024;13(1):6-12, doi:10.1016/j.jshs.2023.10.010), pacompendium.com")

MAX_FILE_BYTES = 50 * 1024 * 1024  # one activity file, after decompression
MAX_ARCHIVE_FILES = 5000
MAX_ARCHIVE_BYTES = 4 * 1024 * 1024 * 1024  # all of an archive's activity files, after decompression

# Sport names found in FIT, TCX and GPX files (lower case, no spaces, dashes or underscores), mapped to a
# general Compendium activity used when the file has no calorie figure.
SPORT_CODES = {
    "running": "12150", "run": "12150", "trailrunning": "12150", "treadmillrunning": "12150", "trackrunning": "12150",
    "walking": "17255", "walk": "17255", "hiking": "17082", "hike": "17082",
    "cycling": "01014", "biking": "01014", "ride": "01014", "roadcycling": "01014", "mountainbiking": "01009",
    "mountain": "01009", "indoorcycling": "01200", "spin": "01270", "virtualride": "01200", "ebiking": "01084",
    "swimming": "18310", "lapswimming": "18240", "openwater": "18300", "openwaterswimming": "18300",
    "rowing": "18070", "indoorrowing": "02071", "elliptical": "02048", "stairclimbing": "17131",
    "training": "02054", "strengthtraining": "02054", "weighttraining": "02054", "cardiotraining": "02060",
    "hiit": "02210", "yoga": "02175", "pilates": "02105",
    "crosscountryskiing": "19090", "nordicski": "19090", "alpineskiing": "19160", "alpineski": "19160",
    "snowboarding": "19201",
    "paddling": "18100", "kayaking": "18100", "canoeing": "18070", "standuppaddleboarding": "18224",
    "tennis": "15675", "soccer": "15610", "basketball": "15055", "golf": "15255", "iceskating": "19030",
    "inlineskating": "15591", "rockclimbing": "15533", "climbing": "15533", "boxing": "15110", "dance": "03070",
}


@dataclass(frozen=True)
class Activity:
    code: str
    met: float
    heading: str
    description: str


@lru_cache
def compendium() -> dict[str, Activity]:
    return {row[0]: Activity(*row) for row in json.loads(COMPENDIUM_FILE.read_text())}


def search_activities(query: str, limit: int = 30) -> list[Activity]:
    terms = query.lower().split()
    if not terms:
        common = dict.fromkeys(SPORT_CODES.values())
        return [compendium()[c] for c in common][:limit]
    hits = [a for a in compendium().values()
            if all(t in f"{a.heading} {a.description} {a.code}".lower() for t in terms)]
    return hits[:limit]


def activity_for_sport(sport: str | None, sub_sport: str | None = None) -> Activity | None:
    for name in (sub_sport, sport):
        key = "".join(c for c in (name or "").lower() if c.isalnum())
        if key in SPORT_CODES:
            return compendium()[SPORT_CODES[key]]
    return None


def weight_on(db: Session, user: User, day: date) -> float | None:
    """The latest weigh-in on or before ``day``, else the profile weight."""
    w = db.scalar(select(BodyMeasurement.weight_kg).where(
        BodyMeasurement.user_id == user.id, BodyMeasurement.date <= day, BodyMeasurement.weight_kg.is_not(None))
        .order_by(BodyMeasurement.date.desc()).limit(1))
    return w or (user.profile.weight_kg if user.profile else None)


def estimate(met: float | None, duration_min: float, weight_kg: float | None, reported_kcal: float | None,
             reported_by: str = "device") -> dict:
    """Net exercise energy (kcal above resting) plus how it was worked out."""
    hours = duration_min / 60
    if reported_kcal:
        if weight_kg:
            resting = weight_kg * hours
            return {"kcal": round(max(0.0, reported_kcal - resting), 1), "kcal_method": reported_by,
                    "calc_note": f"{reported_kcal:.0f} kcal reported, less {resting:.0f} kcal resting "
                                 f"(1 kcal/kg/h × {weight_kg:g} kg × {hours:.2f} h)"}
        return {"kcal": round(reported_kcal, 1), "kcal_method": reported_by,
                "calc_note": f"{reported_kcal:.0f} kcal reported; resting energy not subtracted (no weight recorded)"}
    if met and weight_kg:
        return {"kcal": round(max(0.0, met - 1) * weight_kg * hours, 1), "kcal_method": "compendium",
                "calc_note": f"({met:g} MET − 1) × {weight_kg:g} kg × {hours:.2f} h; MET from the {COMPENDIUM_CITATION}"}
    if met:
        return {"kcal": 0.0, "kcal_method": "none", "calc_note": "Add your weight to estimate energy from METs"}
    return {"kcal": 0.0, "kcal_method": "none", "calc_note": "Choose an activity or enter calories to count energy"}


def daily_kcal(db: Session, user: User, start: date, end: date) -> dict[date, float]:
    """Net exercise energy per local day."""
    out: dict[date, float] = {}
    for day, kcal in db.execute(select(Exercise.date, Exercise.kcal).where(
            Exercise.user_id == user.id, Exercise.date >= start, Exercise.date <= end)):
        out[day] = out.get(day, 0.0) + (kcal or 0.0)
    return out


# --- activity files -----------------------------------------------------------------------------------------

@dataclass
class ParsedActivity:
    started_at: datetime
    sport: str | None
    sub_sport: str | None
    duration_min: float
    distance_m: float | None
    avg_hr: float | None
    reported_kcal: float | None
    source: str  # fit | tcx | gpx


class ActivityFileError(ValueError):
    pass


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _iso(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return _utc(datetime.fromisoformat(text.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def _float(text) -> float | None:
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def parse_fit(data: bytes) -> list[ParsedActivity]:
    out = []
    try:
        with fitdecode.FitReader(io.BytesIO(data)) as reader:
            sessions = [{f.name: f.value for f in frame.fields} for frame in reader
                        if isinstance(frame, fitdecode.FitDataMessage) and frame.name == "session"]
    except fitdecode.FitError as exc:
        raise ActivityFileError(f"Not a readable FIT file ({exc.__class__.__name__})") from None
    for s in sessions:
        start = s.get("start_time")
        seconds = _float(s.get("total_timer_time")) or _float(s.get("total_elapsed_time"))
        if not isinstance(start, datetime) or not seconds:
            continue
        out.append(ParsedActivity(
            started_at=_utc(start), sport=str(s.get("sport") or "") or None, sub_sport=str(s.get("sub_sport") or "") or None,
            duration_min=seconds / 60, distance_m=_float(s.get("total_distance")), avg_hr=_float(s.get("avg_heart_rate")),
            reported_kcal=_float(s.get("total_calories")) or None, source="fit"))
    return out


TCX = "{http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2}"


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1]


def _stream(data: bytes, drop: set[str]):
    """Yield each element of an XML document as it ends, with ``drop`` elements (track points) removed from
    their parent once seen, so a large file is never held as one tree. Entities and DTDs are refused."""
    stack = []
    for event, el in SafeET.iterparse(io.BytesIO(data), events=("start", "end")):
        if event == "start":
            stack.append(el)
            continue
        stack.pop()
        yield el
        if _local(el.tag) in drop and stack:
            stack[-1].remove(el)  # the parent's newest child, so this is quick


def parse_tcx(data: bytes) -> list[ParsedActivity]:
    out = []
    for act in _stream(data, {"Trackpoint"}):
        if act.tag != f"{TCX}Activity":
            continue
        laps = act.findall(f"{TCX}Lap")
        start = _iso(act.findtext(f"{TCX}Id")) or (_iso(laps[0].get("StartTime")) if laps else None)
        seconds = sum(_float(lap.findtext(f"{TCX}TotalTimeSeconds")) or 0 for lap in laps)
        sport = act.get("Sport")
        act.clear()
        if start is None or not seconds:
            continue
        distance = sum(_float(lap.findtext(f"{TCX}DistanceMeters")) or 0 for lap in laps)
        kcal = sum(_float(lap.findtext(f"{TCX}Calories")) or 0 for lap in laps)
        hr_time = [(_float(lap.findtext(f"{TCX}AverageHeartRateBpm/{TCX}Value")),
                    _float(lap.findtext(f"{TCX}TotalTimeSeconds")) or 0) for lap in laps]
        hr_time = [(hr, t) for hr, t in hr_time if hr]
        hr_secs = sum(t for _, t in hr_time)
        out.append(ParsedActivity(
            started_at=start, sport=sport, sub_sport=None, duration_min=seconds / 60,
            distance_m=distance or None, avg_hr=sum(hr * t for hr, t in hr_time) / hr_secs if hr_secs else None,
            reported_kcal=kcal or None, source="tcx"))
    return out


def _haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


# GPX files have no timer, so pauses are worked out from the track: time counts as moving over stretches of at
# least MOVING_WINDOW_S covering MOVING_SPEED_MS or more (slow uphill walking is about 0.5 m/s; GPS jitter
# while standing still stays well under), and a gap of over MAX_GAP_S between points is a pause (devices stop
# recording when paused).
MOVING_WINDOW_S = 30
MOVING_SPEED_MS = 0.25
MAX_GAP_S = 300


class _GpxTrack:
    def __init__(self):
        self.sport: str | None = None
        self.first: datetime | None = None
        self.last: datetime | None = None
        self.elapsed = self.moving = self.distance = 0.0
        self.hr_sum, self.hr_count = 0.0, 0
        self.prev_pos: tuple[float, float] | None = None
        self.prev_time: datetime | None = None
        self.anchor: tuple[datetime, tuple[float, float] | None] | None = None

    def new_segment(self):
        self.prev_pos = self.prev_time = self.anchor = None

    def point(self, time: datetime | None, pos: tuple[float, float] | None, hr: float | None):
        if hr:
            self.hr_sum, self.hr_count = self.hr_sum + hr, self.hr_count + 1
        if pos is not None:
            if self.prev_pos is not None:
                self.distance += _haversine(self.prev_pos, pos)
            self.prev_pos = pos
        if time is None:
            return
        self.first = min(self.first or time, time)
        self.last = max(self.last or time, time)
        if self.prev_time is not None and 0 < (time - self.prev_time).total_seconds() <= MAX_GAP_S:
            self.elapsed += (time - self.prev_time).total_seconds()
        if self.prev_time is not None and (time - self.prev_time).total_seconds() > MAX_GAP_S:
            self.anchor = None  # a pause: start a new stretch
        self.prev_time = time
        if self.anchor is None:
            self.anchor = (time, pos)
            return
        seconds = (time - self.anchor[0]).total_seconds()
        if seconds < MOVING_WINDOW_S:
            return
        start_pos = self.anchor[1]
        if start_pos is None or pos is None or _haversine(start_pos, pos) / seconds >= MOVING_SPEED_MS:
            self.moving += seconds
        self.anchor = (time, pos)

    def activity(self) -> ParsedActivity | None:
        if self.first is None or self.elapsed <= 0:
            return None
        # Hardly any movement (a gym or yoga session that happened to be recorded): count all of it.
        seconds = self.moving if self.moving >= 0.25 * self.elapsed else self.elapsed
        return ParsedActivity(
            started_at=self.first, sport=self.sport, sub_sport=None, duration_min=seconds / 60,
            distance_m=self.distance or None, avg_hr=self.hr_sum / self.hr_count if self.hr_count else None,
            reported_kcal=None, source="gpx")


def parse_gpx(data: bytes) -> list[ParsedActivity]:
    out: list[ParsedActivity] = []
    track: _GpxTrack | None = None
    stack = []
    for event, el in SafeET.iterparse(io.BytesIO(data), events=("start", "end")):
        name = _local(el.tag)
        if event == "start":
            stack.append(el)
            if name == "trk":
                track = _GpxTrack()
            elif name == "trkseg" and track:
                track.new_segment()
            continue
        stack.pop()
        if track is None:
            continue
        if name == "type" and stack and _local(stack[-1].tag) == "trk":
            track.sport = (el.text or "").strip() or None
        elif name == "trkpt":
            lat, lon = _float(el.get("lat")), _float(el.get("lon"))
            time = hr = None
            for child in el.iter():
                tag = _local(child.tag)
                if tag == "time":
                    time = _iso(child.text)
                elif tag == "hr":
                    hr = _float(child.text)
            track.point(time, (lat, lon) if lat is not None and lon is not None else None, hr)
            if stack:
                stack[-1].remove(el)
        elif name == "trk":
            if act := track.activity():
                out.append(act)
            track = None
            el.clear()
    return out


PARSERS = {".fit": parse_fit, ".tcx": parse_tcx, ".gpx": parse_gpx}


def read_limited(fileobj, limit: int = MAX_FILE_BYTES) -> bytes:
    data = fileobj.read(limit + 1)
    if len(data) > limit:
        raise ActivityFileError(f"File is larger than {limit // (1024 * 1024)} MB")
    return data


def parse_file(filename: str, data: bytes) -> list[ParsedActivity]:
    """Parse one activity file (optionally gzip-compressed, as in a Strava export)."""
    name = filename.lower()
    if name.endswith(".gz"):
        name = name[:-3]
        try:
            data = read_limited(gzip.GzipFile(fileobj=io.BytesIO(data)))
        except (OSError, EOFError) as exc:
            raise ActivityFileError(f"Couldn't decompress: {exc}") from None
    parser = PARSERS.get(Path(name).suffix)
    if parser is None:
        raise ActivityFileError("Not a .fit, .tcx or .gpx file")
    try:
        return parser(data.lstrip() if parser is not parse_fit else data)
    except ActivityFileError:
        raise
    except Exception as exc:  # malformed files raise all sorts (XML errors, struct errors, ...)
        raise ActivityFileError(f"Couldn't read the file: {exc.__class__.__name__}") from None


def is_activity_file(name: str) -> bool:
    name = name.lower().removesuffix(".gz")
    return Path(name).suffix in PARSERS


def iter_archive(fileobj) -> Iterator[tuple[str, bytes | ActivityFileError]]:
    """Activity files inside a .zip (e.g. a Strava bulk export), skipping everything else."""
    try:
        archive = zipfile.ZipFile(fileobj)
    except zipfile.BadZipFile:
        raise ActivityFileError("Not a valid .zip file") from None
    members = [m for m in archive.infolist() if not m.is_dir() and is_activity_file(m.filename)]
    if len(members) > MAX_ARCHIVE_FILES:
        raise ActivityFileError(f"The archive holds more than {MAX_ARCHIVE_FILES} activity files")
    total = 0
    for m in members:
        if total > MAX_ARCHIVE_BYTES:
            yield m.filename, ActivityFileError(f"Skipped: the archive holds over {MAX_ARCHIVE_BYTES >> 30} GB of files")
            continue
        with archive.open(m) as f:
            try:
                data = read_limited(f)
            except ActivityFileError as exc:
                yield m.filename, exc
                continue
        total += len(data)
        yield m.filename, data


def external_id(started_at: datetime) -> str:
    """Identifies an activity across re-imports and formats: its start, to the minute."""
    return "start:" + _utc(started_at).strftime("%Y%m%dT%H%M")
