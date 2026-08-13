"""
analysis/llm_analyser.py — LLM integration for intelligent performance analysis
Supports: Anthropic Claude | Google Gemini | OpenAI GPT
Switch via: PERF_LLM_PROVIDER env var  (default: anthropic)

Two modes:
  analyse_with_llm()            → Free-text narrative (used in Section 7)
  analyse_with_llm_structured() → Structured JSON recommendations (used in Section 8)
"""

import json, os, re
from config import LLM_PROVIDER, LLM_MODELS, API_KEYS


def analyse_with_llm(all_data: dict) -> str:
    """
    Send collected performance data to an LLM for intelligent analysis.
    Returns a formatted text analysis.
    """
    api_key = API_KEYS.get(LLM_PROVIDER, "")
    if not api_key:
        return (f"[LLM Analysis] No API key found for provider '{LLM_PROVIDER}'.\n"
                f"Set env var: export {LLM_PROVIDER.upper()}_API_KEY=your_key_here\n"
                f"Skipping LLM analysis.")

    prompt = _build_prompt(all_data)
    model  = LLM_MODELS.get(LLM_PROVIDER, "")

    try:
        if LLM_PROVIDER == "anthropic":
            return _call_anthropic(api_key, model, prompt)
        elif LLM_PROVIDER == "gemini":
            return _call_gemini(api_key, model, prompt)
        elif LLM_PROVIDER == "openai":
            return _call_openai(api_key, model, prompt)
        else:
            return f"[LLM Analysis] Unknown provider: {LLM_PROVIDER}"
    except Exception as e:
        return f"[LLM Analysis] Error calling {LLM_PROVIDER}: {e}"


def _build_prompt(data: dict) -> str:
    """Build a rich analysis prompt from all collected data."""
    device    = data.get("device", {})
    suitability = data.get("suitability", {})
    cold      = data.get("cold_start", {})
    warm      = data.get("warm_start", {})
    snapshots = data.get("snapshots", [])
    battery   = data.get("battery", {})
    network   = data.get("network", {})

    snap_summary = ""
    for s in snapshots:
        p = s.get("parsed", {})
        snap_summary += (
            f"  - [{s['label']}] PSS={p.get('total_pss_mb','?')}MB  "
            f"Native={p.get('native_heap_mb','?')}MB  "
            f"GL={p.get('gl_mtrack_mb','?')}MB  "
            f"CPU={s.get('cpu_pct','?')}%\n"
        )

    prompt = f"""You are a senior Android performance engineer. Analyse the following mobile app performance data and provide:

1. An executive summary (3-4 sentences)
2. Key findings for each area: Start Time, Memory, CPU, GPS/Camera, Battery, Network
3. Industry benchmark comparison for each metric (compare against Google Android Vitals standards)
4. Device suitability verdict with % usage context (what % of device RAM/CPU is the app using)
5. Prioritised recommendations (Critical / High / Medium / Low)
6. Any patterns or anomalies worth noting

Use precise numbers from the data. Be direct and specific. Format findings clearly.

=== DEVICE ===
Model: {device.get('brand','')} {device.get('model','')}
Android: {device.get('android_ver','')} (API {device.get('api_level','')})
RAM: {device.get('ram_total_gb','')} GB total
CPU: {device.get('cpu_cores','')} cores @ {device.get('cpu_max_freq_ghz','')} GHz
Battery: {device.get('battery_mah','')} mAh
Suitability Score: {suitability.get('score','')}/100 ({suitability.get('tier','')})
Suitability Issues: {'; '.join(suitability.get('issues', ['None'])) or 'None'}

=== START TIMES ===
Cold Start: avg={cold.get('avg',0)}ms, min={cold.get('min',0)}ms, max={cold.get('max',0)}ms (Google Good threshold: <2000ms)
Warm Start: avg={warm.get('avg',0)}ms, min={warm.get('min',0)}ms, max={warm.get('max',0)}ms (Google Good threshold: <800ms)

=== MEMORY SNAPSHOTS ===
{snap_summary if snap_summary else '  No snapshots captured'}

=== BATTERY STATS ===
Session duration: {battery.get('session_duration','?')}
Was charging during test: {battery.get('was_charging','unknown')}
Camera sessions: {battery.get('camera_sessions',0)} (indicative; OEM/version-dependent batterystats markers)
Camera total active time: {battery.get('camera_total_sec',0)} seconds
GPS activations: {battery.get('gps_activations',0)}
GPS total active time: {battery.get('gps_total_sec',0)} seconds
Max temperature: {battery.get('temp_max_c','?')} deg C
WorkManager jobs: {battery.get('workmanager_jobs',0)}
Firebase jobs: {battery.get('firebase_jobs',0)}

=== NETWORK / SDK ===
SDKs detected: {', '.join(network.get('sdks_detected', []))}
Total HTTP calls detected: {network.get('total_http_calls',0)}
Total background jobs: {network.get('total_jobs',0)}
Redundant calls: {json.dumps(network.get('redundant_calls', []))}
Top job services: {json.dumps(network.get('top_jobs', []))}

Please provide a thorough professional analysis following the structure above.
Focus on practical, actionable insights relevant to a field driver app used 1-2 trips per day on this specific device.
For each metric, explicitly state the measured value, the industry benchmark, and whether it passes or fails.
"""
    return prompt


# ─────────────────────────────────────────────────────────────────────────────
# Provider implementations
# ─────────────────────────────────────────────────────────────────────────────

def _call_anthropic(api_key, model, prompt):
    import urllib.request, json as _json
    payload = _json.dumps({
        "model":      model,
        "max_tokens": 4096,
        "messages":   [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = _json.loads(resp.read())
    return data["content"][0]["text"]


def _call_gemini(api_key, model, prompt):
    import urllib.request, json as _json
    url     = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = _json.dumps({
        "contents": [{"parts": [{"text": prompt}]}]
    }).encode()

    req = urllib.request.Request(
        url, data=payload,
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = _json.loads(resp.read())
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_openai(api_key, model, prompt):
    import urllib.request, json as _json
    payload = _json.dumps({
        "model":    model,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "content-type":  "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = _json.loads(resp.read())
    return data["choices"][0]["message"]["content"]


# ─────────────────────────────────────────────────────────────────────────────
# Structured JSON analysis (used for Section 8 Prioritised Recommendations)
# ─────────────────────────────────────────────────────────────────────────────

def analyse_with_llm_structured(all_data: dict) -> dict:
    """
    Send collected performance data to an LLM and request structured JSON output.
    Returns a dict with keys: executive_summary, overall_risk, recommendations,
    area_findings.  Falls back to empty dict on any error.

    Each recommendation in the list has:
        priority          : "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
        area              : "GPS" | "Memory" | "CPU" | "Battery" |
                            "Network" | "Start Time" | "Other"
        issue             : short description of the problem
        fix               : concrete fix action
        benchmark_context : measured value vs standard (e.g. "3.3/sec vs 0.1/sec")
        estimated_impact  : expected improvement after fix
    """
    api_key = API_KEYS.get(LLM_PROVIDER, "")
    if not api_key:
        return {}

    prompt = _build_structured_prompt(all_data)
    model  = LLM_MODELS.get(LLM_PROVIDER, "")

    try:
        if LLM_PROVIDER == "anthropic":
            raw = _call_anthropic(api_key, model, prompt)
        elif LLM_PROVIDER == "gemini":
            raw = _call_gemini(api_key, model, prompt)
        elif LLM_PROVIDER == "openai":
            raw = _call_openai(api_key, model, prompt)
        else:
            return {}

        return _parse_structured_response(raw)

    except Exception as e:
        print(f"  [LLM Structured] Error: {e}")
        return {}


def _build_structured_prompt(data: dict) -> str:
    """Build a prompt that instructs the LLM to return only JSON."""
    device    = data.get("device", {})
    suitability = data.get("suitability", {})
    cold      = data.get("cold_start", {})
    warm      = data.get("warm_start", {})
    snapshots = data.get("snapshots", [])
    battery   = data.get("battery", {})
    network   = data.get("network", {})

    snap_summary = ""
    for s in snapshots:
        p = s.get("parsed", {})
        snap_summary += (
            f"  [{s['label']}] PSS={p.get('total_pss_mb','?')}MB "
            f"Native={p.get('native_heap_mb','?')}MB "
            f"GL={p.get('gl_mtrack_mb','?')}MB "
            f"CPU={s.get('cpu_pct','?')}%\n"
        )

    prompt = f"""You are a senior Android performance engineer. Analyse the following test data and return ONLY a JSON object — no prose, no markdown, no explanation, no code fences.

The JSON must have this exact structure:
{{
  "executive_summary": "3-4 sentences covering overall app health",
  "overall_risk": "CRITICAL|HIGH|MEDIUM|LOW",
  "recommendations": [
    {{
      "priority": "CRITICAL|HIGH|MEDIUM|LOW",
      "area": "GPS|Memory|CPU|Battery|Network|Start Time|Other",
      "issue": "concise description of what is wrong",
      "fix": "concrete actionable fix",
      "benchmark_context": "measured value vs industry standard",
      "estimated_impact": "expected improvement after fix"
    }}
  ],
  "area_findings": {{
    "start_time":  "one sentence verdict with measured values",
    "memory":      "one sentence verdict with measured values",
    "cpu":         "one sentence verdict with measured values",
    "gps":         "one sentence verdict with measured values",
    "battery":     "one sentence verdict with measured values",
    "network":     "one sentence verdict with measured values"
  }}
}}

Rules:
- Assign CRITICAL only for issues that affect every driver every shift (e.g. battery drain, crash-level memory)
- Assign HIGH for issues causing noticeable user impact (slow start, significant memory leak)
- Assign MEDIUM for issues worth fixing but not urgent (minor redundancy, cleanup)
- Assign LOW for backlog items with minimal real-world impact
- Base all priority judgements on the real-world usage pattern: 1-2 trips per day on a single device model
- Be specific with numbers — do not repeat generic advice; reference actual measured values
- Sort recommendations: CRITICAL first, then HIGH, MEDIUM, LOW

=== TEST DATA ===

DEVICE: {device.get('brand','')} {device.get('model','')} | Android {device.get('android_ver','')} | {device.get('ram_total_gb','')} GB RAM | {device.get('cpu_cores','')} cores @ {device.get('cpu_max_freq_ghz','')} GHz
SUITABILITY: {suitability.get('score','')}/100 ({suitability.get('tier','')})

START TIMES:
  Cold: avg={cold.get('avg',0)}ms  min={cold.get('min',0)}ms  max={cold.get('max',0)}ms  (Google threshold: <2000ms)
  Warm: avg={warm.get('avg',0)}ms  min={warm.get('min',0)}ms  max={warm.get('max',0)}ms  (Google threshold: <800ms)

MEMORY SNAPSHOTS:
{snap_summary if snap_summary else "  No snapshots captured"}

BATTERY / HARDWARE:
  Session: {battery.get('session_duration','?')}
  Was charging: {battery.get('was_charging','unknown')}
  Camera sessions (indicative): {battery.get('camera_sessions',0)}  Camera active: {battery.get('camera_total_sec',0)}s
  GPS activations: {battery.get('gps_activations',0)}  GPS active: {battery.get('gps_total_sec',0)}s
  Max temperature: {battery.get('temp_max_c','?')} deg C
  WorkManager jobs: {battery.get('workmanager_jobs',0)}  Firebase jobs: {battery.get('firebase_jobs',0)}

NETWORK / SDK:
  SDKs detected: {', '.join(network.get('sdks_detected', []))}
  Total HTTP calls: {network.get('total_http_calls',0)}
  Total background jobs: {network.get('total_jobs',0)}
  Redundant calls: {json.dumps(network.get('redundant_calls', []))}

Return ONLY the JSON object. Start your response with {{ and end with }}.
"""
    return prompt


def _parse_structured_response(raw: str) -> dict:
    """Extract and parse JSON from the LLM response."""
    # Strip markdown fences if present
    cleaned = re.sub(r"```(?:json)?", "", raw).strip()

    # Find the outermost { ... }
    start = cleaned.find("{")
    end   = cleaned.rfind("}")
    if start == -1 or end == -1:
        return {}

    try:
        return json.loads(cleaned[start:end+1])
    except json.JSONDecodeError:
        # Try to extract just the recommendations array as fallback
        try:
            m = re.search(r'"recommendations"\s*:\s*(\[.*?\])', cleaned, re.DOTALL)
            if m:
                recs = json.loads(m.group(1))
                return {"recommendations": recs}
        except Exception:
            pass
        return {}
