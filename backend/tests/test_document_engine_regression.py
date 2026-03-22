import io
import json
from pathlib import Path

from docx import Document

import document_engine


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "document_engine"


def _load_fixture(path: Path) -> dict:
    return json.loads(path.read_text())


def _rendered_text(doc_bytes: bytes) -> str:
    document = Document(io.BytesIO(doc_bytes))
    return "\n".join(paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip())


def test_document_engine_fixtures():
    fixture_paths = sorted(FIXTURE_DIR.glob("*.json"))
    assert fixture_paths, "Expected at least one document engine fixture."

    for path in fixture_paths:
        fixture = _load_fixture(path)
        plan = document_engine.build_document_plan(fixture["doc_type"], fixture["input"])
        expected = fixture["expected"]

        assert plan.theme_id == expected["theme_id"], fixture["id"]
        assert plan.page_budget == expected["page_budget"], fixture["id"]
        assert plan.verification["status"] == expected["verification_status"], fixture["id"]

        if "attempt_count" in expected:
            assert plan.attempt_count == expected["attempt_count"], fixture["id"]
        if "attempt_count_min" in expected:
            assert plan.attempt_count >= expected["attempt_count_min"], fixture["id"]

        actual_actions = [item["action"] for item in plan.repair_history]
        assert actual_actions == expected["repair_actions"], fixture["id"]

        metrics = expected.get("layout_metrics", {})
        for key, value in metrics.items():
            if key.endswith("_max"):
                metric_name = key.removesuffix("_max")
                assert plan.layout_metrics[metric_name] <= value, fixture["id"]
            else:
                assert plan.layout_metrics[key] == value, fixture["id"]

        rendered = document_engine.render_document(plan)
        rendered_text = _rendered_text(rendered)
        for snippet in expected.get("required_text", []):
            assert snippet in rendered_text, f"{fixture['id']}: missing text {snippet!r}"
