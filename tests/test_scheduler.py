"""
Tests for the position-based schedule rule evaluator.

Rules are evaluated in config order — the first matching rule wins.
Put more specific rules before general ones so they take precedence.
"""
from datetime import datetime
import pytest
from frametv.scheduler import evaluate_active_rule


def _dt(year, month, day, hour=12, minute=0):
    return datetime(year, month, day, hour, minute)


def test_first_matching_rule_wins():
    schedules = [
        {"name": "easter-sunday", "date": "04-20", "source": "s1", "mode": "random", "interval_minutes": 60},
        {"name": "every-sunday", "weekdays": ["sunday"], "source": "s2", "mode": "random", "interval_minutes": 60},
        {"name": "default", "source": "s3", "mode": "random", "interval_minutes": 60},
    ]
    # April 20 is a Sunday — easter-sunday is listed first so it wins
    rule = evaluate_active_rule(schedules, _dt(2025, 4, 20))
    assert rule["name"] == "easter-sunday"


def test_general_rule_wins_if_listed_first():
    schedules = [
        {"name": "every-sunday", "weekdays": ["sunday"], "source": "s2", "mode": "random", "interval_minutes": 60},
        {"name": "easter-sunday", "date": "04-20", "source": "s1", "mode": "random", "interval_minutes": 60},
        {"name": "default", "source": "s3", "mode": "random", "interval_minutes": 60},
    ]
    # If general rule is listed first it wins — user controls priority via order
    rule = evaluate_active_rule(schedules, _dt(2025, 4, 20))
    assert rule["name"] == "every-sunday"


def test_specific_date_matches_on_that_day():
    schedules = [
        {"name": "new-year", "date": "2025-01-01", "source": "s1", "mode": "random", "interval_minutes": 60},
        {"name": "default", "source": "s2", "mode": "random", "interval_minutes": 60},
    ]
    assert evaluate_active_rule(schedules, _dt(2025, 1, 1))["name"] == "new-year"
    assert evaluate_active_rule(schedules, _dt(2025, 1, 2))["name"] == "default"


def test_annual_date_matches_every_year():
    schedules = [
        {"name": "new-year", "date": "01-01", "source": "s1", "mode": "random", "interval_minutes": 60},
        {"name": "default", "source": "s2", "mode": "random", "interval_minutes": 60},
    ]
    assert evaluate_active_rule(schedules, _dt(2025, 1, 1))["name"] == "new-year"
    assert evaluate_active_rule(schedules, _dt(2026, 1, 1))["name"] == "new-year"
    assert evaluate_active_rule(schedules, _dt(2025, 1, 2))["name"] == "default"


def test_date_range_includes_endpoints():
    schedules = [
        {"name": "june", "date_range": {"start": "06-01", "end": "06-30"}, "source": "s", "mode": "random", "interval_minutes": 60},
        {"name": "default", "source": "d", "mode": "random", "interval_minutes": 60},
    ]
    assert evaluate_active_rule(schedules, _dt(2025, 6, 1))["name"] == "june"
    assert evaluate_active_rule(schedules, _dt(2025, 6, 30))["name"] == "june"
    assert evaluate_active_rule(schedules, _dt(2025, 7, 1))["name"] == "default"


def test_year_wrap_date_range():
    schedules = [
        {"name": "holiday", "date_range": {"start": "12-15", "end": "01-05"}, "source": "s", "mode": "random", "interval_minutes": 60},
        {"name": "default", "source": "d", "mode": "random", "interval_minutes": 60},
    ]
    assert evaluate_active_rule(schedules, _dt(2025, 12, 20))["name"] == "holiday"
    assert evaluate_active_rule(schedules, _dt(2026, 1, 3))["name"] == "holiday"
    assert evaluate_active_rule(schedules, _dt(2025, 6, 1))["name"] == "default"


def test_weekday_matching():
    schedules = [
        {"name": "weekend", "weekdays": ["saturday", "sunday"], "source": "s", "mode": "random", "interval_minutes": 60},
        {"name": "default", "source": "d", "mode": "random", "interval_minutes": 60},
    ]
    # 2025-06-07 is Saturday
    assert evaluate_active_rule(schedules, _dt(2025, 6, 7))["name"] == "weekend"
    # 2025-06-08 is Sunday
    assert evaluate_active_rule(schedules, _dt(2025, 6, 8))["name"] == "weekend"
    # 2025-06-09 is Monday
    assert evaluate_active_rule(schedules, _dt(2025, 6, 9))["name"] == "default"


def test_time_window_boundary():
    schedules = [
        {"name": "morning", "time_window": {"start": "06:00", "end": "09:00"}, "source": "s", "mode": "random", "interval_minutes": 60},
        {"name": "default", "source": "d", "mode": "random", "interval_minutes": 60},
    ]
    assert evaluate_active_rule(schedules, _dt(2025, 6, 9, 6, 0))["name"] == "morning"
    assert evaluate_active_rule(schedules, _dt(2025, 6, 9, 9, 0))["name"] == "morning"
    assert evaluate_active_rule(schedules, _dt(2025, 6, 9, 9, 1))["name"] == "default"
    assert evaluate_active_rule(schedules, _dt(2025, 6, 9, 5, 59))["name"] == "default"


def test_default_matches_when_nothing_else_does():
    schedules = [
        {"name": "weekend", "weekdays": ["saturday", "sunday"], "source": "s", "mode": "random", "interval_minutes": 60},
        {"name": "default", "source": "d", "mode": "random", "interval_minutes": 60},
    ]
    # Monday — no match besides default
    assert evaluate_active_rule(schedules, _dt(2025, 6, 9))["name"] == "default"


def test_single_rule_always_returns_it():
    schedules = [{"name": "only", "source": "s", "mode": "random", "interval_minutes": 60}]
    assert evaluate_active_rule(schedules, _dt(2025, 1, 1))["name"] == "only"


def test_multiple_conditions_first_match_wins():
    # Two date-range rules that both cover the same day
    schedules = [
        {"name": "narrow", "date_range": {"start": "06-01", "end": "06-07"}, "source": "s", "mode": "random", "interval_minutes": 60},
        {"name": "broad", "date_range": {"start": "06-01", "end": "06-30"}, "source": "s", "mode": "random", "interval_minutes": 60},
        {"name": "default", "source": "d", "mode": "random", "interval_minutes": 60},
    ]
    # June 5 — both ranges match; narrow is first so it wins
    assert evaluate_active_rule(schedules, _dt(2025, 6, 5))["name"] == "narrow"
    # June 15 — only broad matches
    assert evaluate_active_rule(schedules, _dt(2025, 6, 15))["name"] == "broad"
