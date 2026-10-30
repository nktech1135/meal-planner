from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LogEntry, User
from app.nutrients import TRUST_RANK
from app.services.nutrition import add_into, rounded
from app.services.targets import compute_targets


def user_tz(user: User) -> ZoneInfo:
    return ZoneInfo((user.profile.timezone if user.profile else None) or "UTC")


def local_today(user: User) -> date:
    return datetime.now(user_tz(user)).date()


def day_bounds(user: User, day: date) -> tuple[datetime, datetime]:
    tz = user_tz(user)
    start = datetime.combine(day, time.min, tzinfo=tz)
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


def entries_between(db: Session, user: User, start: date, end: date) -> list[LogEntry]:
    lo, _ = day_bounds(user, start)
    _, hi = day_bounds(user, end)
    return list(db.scalars(
        select(LogEntry).where(LogEntry.user_id == user.id, LogEntry.consumed_at >= lo, LogEntry.consumed_at < hi)
        .order_by(LogEntry.consumed_at)
    ))


def local_date(user: User, dt: datetime) -> date:
    if dt.tzinfo is None:  # SQLite returns naive UTC
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(user_tz(user)).date()


def evaluate(totals: dict, supplement_totals: dict, targets: dict, uncounted: dict | None = None) -> list[dict]:
    """Compare intake to each target; upper limits with supplemental scope use supplement intake only.

    ``uncounted`` lists label amounts per nutrient that couldn't be converted; a nutrient that
    looks low but has such amounts is reported as "partial" rather than "below".
    """
    uncounted = uncounted or {}
    rows = []
    for code, t in targets.items():
        amount = totals.get(code, 0.0)
        status = "ok"
        if t.get("min") is not None and amount < t["min"]:
            status = "below"
        elif t.get("target") is not None and amount < t["target"]:
            status = "below"
        limit_amount = supplement_totals.get(code, 0.0) if t.get("ul_scope") == "supplemental" else amount
        if t.get("max") is not None and limit_amount > t["max"]:
            status = "above_max"
        if status == "below" and uncounted.get(code):
            status = "partial"
        rows.append({"code": code, "amount": round(amount, 3), "limit_amount": round(limit_amount, 3), "status": status,
                     "uncounted": uncounted.get(code, []), **t})
    return rows


def day_summary(db: Session, user: User, day: date) -> dict:
    entries = entries_between(db, user, day, day)
    totals: dict[str, float] = {}
    supplement_totals: dict[str, float] = {}
    others: dict[tuple[str, str], float] = {}
    uncounted: dict[str, list[dict]] = {}
    energy_by_trust: dict[str, float] = {}
    for e in entries:
        add_into(totals, e.nutrients)
        if e.is_supplement:
            add_into(supplement_totals, e.nutrients)
        energy_by_trust[e.trust_level] = energy_by_trust.get(e.trust_level, 0) + e.nutrients.get("energy_kcal", 0)
        for c in e.other_components or []:
            if c.get("nutrient_code") and c.get("amount") is not None:
                uncounted.setdefault(c["nutrient_code"], []).append({
                    "name": c["name"], "amount": round(c["amount"], 3), "unit": c.get("unit"), "item": e.label,
                    "entry_id": e.id, "food_id": e.food_id, "resolvable": c.get("reason") == "form"})
            if c.get("amount") is not None:
                key = (c["name"], c.get("unit") or "")
                others[key] = others.get(key, 0) + c["amount"]
    target_info = compute_targets(user.profile, day)
    evaluation = evaluate(totals, supplement_totals, target_info["targets"], uncounted)
    alerts = [
        f"{r['code']}: {r['limit_amount']:g} exceeds the upper limit {r['max']:g}"
        + (" (from supplements)" if r.get("ul_scope") == "supplemental" else "")
        for r in evaluation if r["status"] == "above_max"
    ]
    return {
        "date": day.isoformat(),
        "entries": entries,
        "totals": rounded(totals),
        "supplement_totals": rounded(supplement_totals),
        "other_components": [{"name": n, "unit": u, "amount": round(a, 3)} for (n, u), a in sorted(others.items())],
        "evaluation": evaluation,
        "warnings": target_info["warnings"],
        "alerts": alerts,
        "energy_by_trust": {k: round(v, 1) for k, v in sorted(energy_by_trust.items(), key=lambda kv: TRUST_RANK[kv[0]])},
    }


def range_totals(db: Session, user: User, start: date, end: date) -> list[dict]:
    by_day: dict[date, dict[str, float]] = {}
    counts: dict[date, int] = {}
    for e in entries_between(db, user, start, end):
        d = local_date(user, e.consumed_at)
        add_into(by_day.setdefault(d, {}), e.nutrients)
        counts[d] = counts.get(d, 0) + 1
    days = []
    d = start
    while d <= end:
        days.append({"date": d.isoformat(), "entries": counts.get(d, 0), "totals": rounded(by_day.get(d, {}))})
        d += timedelta(days=1)
    return days
