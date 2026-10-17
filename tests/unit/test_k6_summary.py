"""tools/k6_summary.py: the load-test report that leaves the CI runner."""

from __future__ import annotations

from tools.k6_summary import report

# A sentinel, not a credential: the export's setup_data holds real access tokens in a run.
TOKEN = "setup-data-sentinel-must-not-leak"


def _summary(**extra: dict) -> dict:
    metrics = {
        "http_req_duration{slo:api}": {"p(99)": 357.2, "thresholds": {"p(99)<1000": False}},
        "http_req_failed{slo:api}": {"value": 0.0009, "thresholds": {"rate<0.005": False}},
        "rate_limited": {"count": 9, "thresholds": {"count==0": True}},
        "http_req_duration{name:playback.release}": {
            "count": 1015, "med": 9.5, "p(95)": 71, "p(99)": 175, "max": 494, "thresholds": {"max>=0": False},
        },
        "rate_limited{name:playback.release}": {"count": 9, "thresholds": {"count>=0": False}},
        "http_req_duration{name:titles.rails}": {
            "count": 1032, "med": 59, "p(95)": 345, "p(99)": 700, "max": 1174, "thresholds": {"max>=0": False},
        },
        "http_reqs": {"count": 10759, "rate": 24.4},
        "iterations": {"count": 1269},
        "vus_max": {"max": 202},
        **extra,
    }  # fmt: skip
    return {"metrics": metrics, "setup_data": {"tokens": [TOKEN], "refs": ["catalog:1"]}}


def test_thresholds_with_their_values_and_results():
    text = report(_summary())
    assert "| `http_req_duration{slo:api}` `p(99)<1000` | 357 ms | ✅ |" in text
    assert "| `http_req_failed{slo:api}` `rate<0.005` | 0.09% | ✅ |" in text
    assert "| `rate_limited` `count==0` | 9 | ❌ failed |" in text


def test_429s_are_attributed_to_their_endpoint():
    text = report(_summary())
    assert "| `playback.release` | 1,015 | **9** | 9.5 ms | 71 ms | 175 ms | 494 ms |" in text
    assert "| `titles.rails` | 1,032 | 0 | 59 ms |" in text  # no submetric sample → 0, not missing


def test_reporting_submetrics_are_not_shown_as_thresholds():
    text = report(_summary())
    assert "max>=0" not in text
    assert "count>=0" not in text


def test_setup_data_never_reaches_the_report():
    text = report(_summary())
    assert TOKEN not in text
    assert "catalog:1" not in text
