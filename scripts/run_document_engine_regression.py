#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
FIXTURE_DIR = BACKEND_DIR / "tests" / "fixtures" / "document_engine"
VERIFY_SCRIPT = ROOT / "scripts" / "verify_docx_layout.py"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate document-engine regression artifacts from named fixtures and "
            "optionally run the local DOCX layout verifier over the outputs."
        )
    )
    parser.add_argument(
        "--fixture",
        action="append",
        default=[],
        help="Run only specific fixture ids. May be passed multiple times.",
    )
    parser.add_argument(
        "--outdir",
        default=str(ROOT / "tmp" / "document_engine_regression"),
        help="Directory where generated docs and summaries should be written.",
    )
    parser.add_argument(
        "--render",
        action="store_true",
        help="After generating fixture outputs, run the local DOCX layout verifier on them.",
    )
    parser.add_argument(
        "--python",
        default=str(BACKEND_DIR / ".venv" / "bin" / "python"),
        help="Python executable to use for the backend generation step.",
    )
    return parser.parse_args()


def load_fixtures(selected_ids: set[str]) -> list[dict]:
    fixtures = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        fixture = json.loads(path.read_text())
        if selected_ids and fixture["id"] not in selected_ids:
            continue
        fixtures.append(fixture)
    return fixtures


def generate_outputs(python_bin: str, fixtures: list[dict], outdir: Path) -> tuple[list[str], dict[str, int]]:
    outdir.mkdir(parents=True, exist_ok=True)
    fixture_payload = json.dumps(fixtures)
    script = """
import json
import sys
from pathlib import Path
import document_engine

fixtures = json.loads(sys.argv[1])
outdir = Path(sys.argv[2])
summary = []
generated_paths = []
budgets = {}

for fixture in fixtures:
    plan = document_engine.build_document_plan(fixture["doc_type"], fixture["input"])
    filename = f'{fixture["id"]}.docx'
    output_path = outdir / filename
    output_path.write_bytes(document_engine.render_document(plan))
    generated_paths.append(str(output_path))
    budgets[filename] = plan.page_budget
    summary.append({
        "id": fixture["id"],
        "doc_type": fixture["doc_type"],
        "theme_id": plan.theme_id,
        "attempt_count": plan.attempt_count,
        "verification": plan.verification,
        "repair_history": plan.repair_history,
        "layout_metrics": plan.layout_metrics,
        "output_path": str(output_path),
    })

(outdir / "summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps({"generated_paths": generated_paths, "budgets": budgets}, indent=2))
"""
    result = subprocess.run(
        [python_bin, "-c", script, fixture_payload, str(outdir)],
        check=True,
        capture_output=True,
        text=True,
        cwd=str(BACKEND_DIR),
    )
    payload = json.loads(result.stdout)
    return payload["generated_paths"], payload["budgets"]


def run_render_verification(paths: list[str], budgets: dict[str, int], outdir: Path) -> int:
    command = [sys.executable, str(VERIFY_SCRIPT), *paths]
    for filename, budget in sorted(budgets.items()):
        command.extend(["--expect", f"{filename}={budget}"])
    command.extend(["--outdir", str(outdir / "rendered")])
    return subprocess.run(command, cwd=str(ROOT)).returncode


def main() -> int:
    args = parse_args()
    fixtures = load_fixtures(set(args.fixture))
    if not fixtures:
        print("No fixtures selected.", file=sys.stderr)
        return 2

    outdir = Path(args.outdir).resolve()
    generated_paths, budgets = generate_outputs(args.python, fixtures, outdir)
    print(f"Generated {len(generated_paths)} fixture document(s) in {outdir}")
    print(f"Summary: {outdir / 'summary.json'}")

    if args.render:
        print("Running local DOCX render verification...")
        return run_render_verification(generated_paths, budgets, outdir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
