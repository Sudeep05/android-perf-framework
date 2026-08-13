"""
analysis/benchmarks.py — Industry standard benchmarks for Android app performance
Sources: Google Android Vitals, Android Developer Documentation, Firebase Performance
"""

GOOGLE_VITALS = {
    # App Start Times
    "cold_start": {
        "excellent_ms": 1000,
        "good_ms":      2000,
        "acceptable_ms":5000,
        "source":       "Google Android Vitals — Slow rendering threshold",
    },
    "warm_start": {
        "excellent_ms": 200,
        "good_ms":      800,
        "acceptable_ms":2000,
        "source":       "Google Android Vitals",
    },
    "hot_start": {
        "excellent_ms": 100,
        "good_ms":      200,
        "acceptable_ms":500,
        "source":       "Google Android Vitals",
    },

    # Memory
    "idle_pss_mb": {
        "excellent": 50,
        "good":      100,
        "acceptable":150,
        "source":    "Android Developer — Memory Management Best Practices",
    },
    "active_pss_mb": {
        "excellent": 100,
        "good":      200,
        "acceptable":300,
        "source":    "Android Developer — App memory overview",
    },
    "gl_mtrack_mb": {
        "excellent": 10,
        "good":      20,
        "acceptable":40,
        "source":    "Android Graphics Memory guidance",
    },
    "swap_pss_mb": {
        "excellent": 0,
        "good":      10,
        "acceptable":50,
        "source":    "Android Memory Profiler — Low Memory Killer thresholds",
    },
    "memory_growth_per_session_pct": {
        "excellent": 10,
        "good":      30,
        "acceptable":60,
        "source":    "Android Memory Leak detection guidance",
    },

    # CPU
    "idle_cpu_pct": {
        "excellent": 2,
        "good":      5,
        "acceptable":10,
        "source":    "Google Play — Android Vitals battery drain signals",
    },
    "active_cpu_pct": {
        "excellent": 30,
        "good":      50,
        "acceptable":80,
        "source":    "Android Performance Patterns — CPU usage",
    },
    "cpu_spike_max_pct": {
        "excellent": 100,
        "good":      200,
        "acceptable":300,
        "source":    "Brief spikes acceptable; sustained >100% is problematic",
    },

    # GPS
    "gps_poll_interval_sec": {
        "navigation":  1,
        "field_work":  10,
        "background":  60,
        "source":      "Android Location — Battery optimisation best practices",
    },
    "gps_activations_per_hour": {
        "excellent": 60,
        "good":      120,
        "acceptable":360,
        "source":    "Android Location Power guide",
    },

    # Battery
    "battery_drain_per_hour_pct": {
        "excellent": 3,
        "good":      6,
        "acceptable":12,
        "source":    "Google Play — Bad behaviour battery threshold >6%/hr",
    },
    "wakelock_duration_sec": {
        "excellent": 1,
        "good":      5,
        "acceptable":30,
        "source":    "Android Vitals — Stuck partial wakelock threshold",
    },
}


def rate(value, metric_key, higher_is_worse=True):
    """
    Rate a value against benchmarks.
    Returns: ('EXCELLENT'|'GOOD'|'ACCEPTABLE'|'POOR', str delta_vs_good)
    """
    if metric_key not in GOOGLE_VITALS:
        return ("UNKNOWN", "")

    bm = GOOGLE_VITALS[metric_key]
    exc = bm.get("excellent") or bm.get("excellent_ms") or bm.get("excellent_pct") or 0
    good = bm.get("good") or bm.get("good_ms") or bm.get("good_pct") or 0
    acc  = bm.get("acceptable") or bm.get("acceptable_ms") or bm.get("acceptable_pct") or 0

    if higher_is_worse:
        if value <= exc:  rating = "EXCELLENT"
        elif value <= good: rating = "GOOD"
        elif value <= acc:  rating = "ACCEPTABLE"
        else: rating = "POOR"
        delta = f"{round(value - good, 1)} vs good threshold of {good}"
    else:
        # Higher is better (e.g. battery life)
        if value >= exc:  rating = "EXCELLENT"
        elif value >= good: rating = "GOOD"
        elif value >= acc:  rating = "ACCEPTABLE"
        else: rating = "POOR"
        delta = f"{value} vs good threshold of {good}"

    return (rating, delta)


def get_source(metric_key):
    bm = GOOGLE_VITALS.get(metric_key, {})
    return bm.get("source", "Android Developer Documentation")
