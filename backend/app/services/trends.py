"""Multi-day views: averages against targets, daily series, weight trend and an adaptive energy estimate."""

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BodyMeasurement, User
from app.services.exercise import daily_kcal
from app.services.nutrition import add_into
from app.services.summary import entries_between, evaluate, local_date
from app.services.targets import compute_targets

# Energy in a kilogram of body-weight change. A common approximation (Wishnofsky's
# 3,500 kcal/lb); real tissue composition varies, so the estimate below is rough.
KCAL_PER_KG = 7700
TREND_ALPHA = 0.1  # exponential smoothing of daily weights (each day moves the trend 10% toward the scale)
MIN_DAYS_FOR_ESTIMATE = 14
MIN_LOGGED_FRACTION = 0.7


def weight_trend(measurements: list[BodyMeasurement]) -> list[dict]:
    out, trend = [], None
    for m in sorted((m for m in measurements if m.weight_kg), key=lambda m: m.date):
        trend = m.weight_kg if trend is None else trend + TREND_ALPHA * (m.weight_kg - trend)
        out.append({"date": m.date.isoformat(), "weight_kg": m.weight_kg, "trend_kg": round(trend, 2)})
    return out


def trends(db: Session, user: User, start: date, end: date) -> dict:
    span = (end - start).days + 1
    daily: dict[date, dict[str, float]] = {}
    supplements: dict[date, dict[str, float]] = {}
    for e in entries_between(db, user, start, end):
        d = local_date(user, e.consumed_at)
        add_into(daily.setdefault(d, {}), e.nutrients)
        if e.is_supplement:
            add_into(supplements.setdefault(d, {}), e.nutrients)
    logged = sorted(daily)
    n = len(logged)

    averages: dict[str, float] = {}
    supp_averages: dict[str, float] = {}
    for d in logged:
        add_into(averages, daily[d])
        add_into(supp_averages, supplements.get(d, {}))
    if n:
        averages = {k: v / n for k, v in averages.items()}
        supp_averages = {k: v / n for k, v in supp_averages.items()}

    # Exercise raises a day's energy target, so averages are judged against the average day's target
    # and each day against its own.
    exercise = daily_kcal(db, user, start, end)
    targets = compute_targets(user.profile, end, sum(exercise.get(d, 0) for d in logged) / n if n else 0)
    rest_day = compute_targets(user.profile, end)["targets"]
    day_targets = {d: compute_targets(user.profile, end, exercise[d])["targets"] if exercise.get(d) else rest_day
                   for d in logged}
    evaluation = evaluate(averages, supp_averages, targets["targets"])
    for row in evaluation:
        met = 0
        for d in logged:
            t = day_targets[d].get(row["code"], row)
            day_eval = evaluate(daily[d], supplements.get(d, {}), {row["code"]: {k: t.get(k) for k in (
                "min", "target", "max", "ul_scope", "max_is_limit")}})[0]
            met += day_eval["status"] == "ok"
        row["days_ok"] = met
        row["amount"] = round(row["amount"], 3)

    measurements = list(db.scalars(select(BodyMeasurement).where(
        BodyMeasurement.user_id == user.id, BodyMeasurement.date >= start - timedelta(days=30),
        BodyMeasurement.date <= end).order_by(BodyMeasurement.date)))
    trend = weight_trend(measurements)
    in_window = [t for t in trend if date.fromisoformat(t["date"]) >= start]

    return {
        "start": start.isoformat(), "end": end.isoformat(), "days": span, "logged_days": n,
        "daily": [{"date": (start + timedelta(days=i)).isoformat(),
                   "logged": (start + timedelta(days=i)) in daily,
                   "totals": {k: round(v, 3) for k, v in daily.get(start + timedelta(days=i), {}).items()}}
                  for i in range(span)],
        "averages": {k: round(v, 3) for k, v in averages.items()},
        "evaluation": evaluation,
        "weight": in_window,
        "body": [{"date": m.date.isoformat(), "weight_kg": m.weight_kg, "body_fat_pct": m.body_fat_pct,
                  "waist_cm": m.waist_cm} for m in measurements if m.date >= start],
        "energy_estimate": energy_estimate(daily, in_window, start, end),
        "exercise_kcal": {d.isoformat(): round(v, 1) for d, v in sorted(exercise.items())},
        "warnings": targets["warnings"],
    }


def energy_estimate(daily: dict[date, dict], trend: list[dict], start: date, end: date) -> dict:
    """Maintenance energy from what was eaten and how the weight trend moved.

    intake − (trend change × 7,700 kcal/kg ÷ days). Needs at least 14 days between the first and last
    weigh-in and food logged on at least 70% of those days; otherwise explains what's missing.
    """
    method = ("Average logged intake minus the energy implied by the weight-trend change "
              f"({KCAL_PER_KG:,} kcal per kg, an approximation).")
    if len(trend) < 2:
        return {"available": False, "reason": "Log your weight at least a few times a week.", "method": method}
    first, last = date.fromisoformat(trend[0]["date"]), date.fromisoformat(trend[-1]["date"])
    days = (last - first).days
    if days < MIN_DAYS_FOR_ESTIMATE:
        return {"available": False, "reason": f"Needs {MIN_DAYS_FOR_ESTIMATE} days between first and last weigh-in "
                f"(have {days}).", "method": method}
    window = [first + timedelta(days=i) for i in range(days + 1)]
    logged = [d for d in window if d in daily]
    fraction = len(logged) / len(window)
    if fraction < MIN_LOGGED_FRACTION:
        return {"available": False, "reason": f"Food was logged on {fraction:.0%} of those days; needs "
                f"{MIN_LOGGED_FRACTION:.0%} so missing days don't skew the average.", "method": method}
    intake = sum(daily[d].get("energy_kcal", 0) for d in logged) / len(logged)
    change = trend[-1]["trend_kg"] - trend[0]["trend_kg"]
    estimate = intake - change * KCAL_PER_KG / days
    return {
        "available": True, "maintenance_kcal": round(estimate), "average_intake_kcal": round(intake),
        "trend_change_kg": round(change, 2), "days": days, "logged_fraction": round(fraction, 2), "method": method,
    }
