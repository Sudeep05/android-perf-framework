"""
modules/network.py — Network call and SDK analyser
"""

import re, os, json
from collections import Counter


def analyse_network_logs(network_log_path, app_log_path, package):
    """Analyse network_calls.txt and app_logs.txt for SDK usage and redundancy."""
    result = {
        "sdks_detected":      [],
        "redundant_calls":    [],
        "workmanager_growth": {},
        "total_jobs":         0,
    }

    # Read files
    net_content = _read(network_log_path)
    app_content = _read(app_log_path)

    # ── SDK Detection ────────────────────────────────────────────────────
    sdk_patterns = {
        "Firebase Crashlytics": r"FirebaseCrashlytics",
        "Firebase Analytics":   r"FA\s|Firebase Analytics",
        "Firebase Sessions":    r"FirebaseSessions",
        "Google Play Core":     r"PlayCore",
        "WorkManager":          r"WM-|WorkManager|SystemJobService",
        "Google Datatransport": r"datatransport",
        "OkHttp":               r"okhttp",
        "Retrofit":             r"retrofit",
        "GMS Location":         r"FusedLocation|NetworkLocation",
        "New Relic":            r"NewRelic|com\.newrelic",
        "Sentry":               r"io\.sentry",
        "Datadog":              r"com\.datadog",
    }
    for sdk, pattern in sdk_patterns.items():
        if re.search(pattern, app_content, re.IGNORECASE) or \
           re.search(pattern, net_content, re.IGNORECASE):
            result["sdks_detected"].append(sdk)

    # ── Redundant Call Detection ─────────────────────────────────────────
    # Play Core double-call
    update_calls = re.findall(
        r"(\d{2}:\d{2}:\d{2}\.\d+).*?requestUpdateInfo\(" + re.escape(package) + r"\)",
        app_content
    )
    if len(update_calls) >= 2:
        result["redundant_calls"].append({
            "type":        "Google Play Core — requestUpdateInfo double-call",
            "occurrences": len(update_calls),
            "evidence":    f"Called {len(update_calls)} times; first two at "
                           f"{update_calls[0]} and {update_calls[1]}",
            "severity":    "LOW",
            "fix":         "Consolidate to single call in one lifecycle method",
        })

    # WorkManager cache growth (read from snapshots if available)
    wm_caches = re.findall(
        r"(\d+/\d+/\d+)\s+/.*?androidx\.work\.workdb",
        app_content
    )
    if len(wm_caches) >= 2:
        result["workmanager_growth"] = {
            "first": wm_caches[0],
            "last":  wm_caches[-1],
        }

    # Count job activations per service
    job_matches = re.findall(r"\+job=.*?:\"(.+?)\"", net_content)
    job_counter = Counter(job_matches)
    result["total_jobs"] = sum(job_counter.values())
    result["top_jobs"]   = job_counter.most_common(5)

    # HTTP calls (if visible in logs)
    http_urls = re.findall(r"https?://[^\s\"']+", net_content)
    domain_counter = Counter()
    for url in http_urls:
        m = re.match(r"https?://([^/]+)", url)
        if m:
            domain_counter[m.group(1)] += 1
    result["api_domains"]      = domain_counter.most_common(10)
    result["total_http_calls"] = len(http_urls)

    return result


def _read(path):
    if not path or not os.path.exists(path):
        return ""
    try:
        with open(path, "r", errors="replace") as f:
            return f.read()
    except Exception:
        return ""
