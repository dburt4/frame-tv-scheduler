from __future__ import annotations
from datetime import datetime, time as dtime, date as ddate


def _match_date(rule: dict, now: datetime) -> bool:
    raw = rule["date"]
    parts = raw.split("-")
    if len(parts) == 3:
        target = ddate(int(parts[0]), int(parts[1]), int(parts[2]))
        return now.date() == target
    # MM-DD annual
    m, d = int(parts[0]), int(parts[1])
    return now.month == m and now.day == d


def _match_date_range(rule: dict, now: datetime) -> bool:
    dr = rule["date_range"]
    sm, sd = [int(x) for x in dr["start"].split("-")]
    em, ed = [int(x) for x in dr["end"].split("-")]
    cur = (now.month, now.day)
    start = (sm, sd)
    end = (em, ed)
    if start <= end:
        return start <= cur <= end
    # wraps across year boundary (e.g. Dec 15 – Jan 5)
    return cur >= start or cur <= end


def _match_weekdays(rule: dict, now: datetime) -> bool:
    day_name = now.strftime("%A").lower()
    return day_name in [d.lower() for d in rule["weekdays"]]


def _match_time_window(rule: dict, now: datetime) -> bool:
    tw = rule["time_window"]
    start = dtime.fromisoformat(tw["start"])
    end = dtime.fromisoformat(tw["end"])
    t = now.time()
    if start <= end:
        return start <= t <= end
    # overnight wrap not supported in v1
    return False


def _matches(rule: dict, now: datetime) -> bool:
    if rule.get("date"):
        return _match_date(rule, now)
    if rule.get("date_range"):
        return _match_date_range(rule, now)
    if rule.get("weekdays"):
        return _match_weekdays(rule, now)
    if rule.get("time_window"):
        return _match_time_window(rule, now)
    return True  # default rule


def evaluate_active_rule(schedules: list[dict], now: datetime) -> dict:
    """Return the first matching schedule rule for `now`.

    Rules are evaluated in config order — the first rule that matches wins.
    Put more specific rules (e.g. "Easter Sunday") before general ones
    (e.g. "every Sunday") so they take precedence.
    """
    for rule in schedules:
        if _matches(rule, now):
            return rule
    # Fallback: should not happen if config ends with an unconditional default
    return schedules[-1]


def find_default_rule(schedules: list[dict]) -> dict | None:
    """Return the first unconditional rule (no date/range/weekday/time conditions).

    This is the rule used as a fallback when the active rule's source fails.
    Returns None if no unconditional rule exists.
    """
    for rule in schedules:
        if not any(rule.get(k) for k in ("date", "date_range", "weekdays", "time_window")):
            return rule
    return None
