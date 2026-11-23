from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integrations"))
from print_spec_worker import grounded_result, review_report


SPEC = "Cover width 38 mm +/-0.3 mm. CAD cover-v4.step"


def test_range_uses_the_revised_filename_and_decimal_dimensions():
    assert grounded_result(SPEC, "cover-v4.step | 38 | 0.3 |") == "cover-v4.step: 37.7–38.3 mm"


@pytest.mark.parametrize(("spec", "answer"), [
    (SPEC, "cover-v3.step | 38 | 0.3"),
    (SPEC, "cover-v4.step | 38 | 0.2"),
    (SPEC, "cover-v4.step | 38 | 0.3 | 0.1"),
    (SPEC + ". Alternate CAD cover-v3.step", "cover-v4.step | 38 | 0.3"),
    (SPEC + ". Alternate width 41 mm", "cover-v4.step | 38 | 0.3"),
    (SPEC.replace("+/-0.3 mm", ""), "cover-v4.step | 38 | 0.3"),
    (SPEC.replace("0.3", "40"), "cover-v4.step | 38 | 40"),
])
def test_unsupported_result_requests_clarification(spec, answer):
    job = {"taskId": "card-a", "sendId": "send-a",
           "brief": {"source": "card:a@3", "revision": "r3", "spec": spec}}
    report = review_report(job, answer)
    assert report["checklist"][0]["status"] == "pending"
    assert report["result"].startswith("Clarification requested")
    assert report["taskId"] == "card-a" and report["sendId"] == "send-a"
