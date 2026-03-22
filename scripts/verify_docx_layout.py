#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RENDER_SCRIPT = ROOT / "scripts" / "render_docx_macos.sh"
PAGES_RE = re.compile(r"^Pages:\s+(\d+)\s*$", re.MULTILINE)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render DOCX files through the local macOS LibreOffice pipeline and "
            "verify that the output stays within the expected page budget."
        )
    )
    parser.add_argument(
        "inputs",
        nargs="+",
        help="Absolute or relative paths to .docx files to verify.",
    )
    parser.add_argument(
        "--default-page-budget",
        type=int,
        default=1,
        help="Default allowed page count when no per-file override is provided.",
    )
    parser.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="NAME=PAGES",
        help=(
            "Override the page budget for a specific file. NAME can be either the "
            "full filename or the stem. Example: --expect resume.docx=2"
        ),
    )
    parser.add_argument(
        "--outdir",
        help="Directory for rendered PDFs, PNGs, and LibreOffice logs. Defaults to a temp directory.",
    )
    parser.add_argument(
        "--render-script",
        default=str(DEFAULT_RENDER_SCRIPT),
        help=f"Render helper to use. Defaults to {DEFAULT_RENDER_SCRIPT}",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the verification result as JSON.",
    )
    return parser.parse_args()


def parse_expectations(raw_expectations: list[str]) -> dict[str, int]:
    expectations: dict[str, int] = {}
    for item in raw_expectations:
        name, separator, pages = item.partition("=")
        if not separator:
            raise ValueError(f"Invalid --expect value: {item!r}. Expected NAME=PAGES.")
        normalized_name = name.strip()
        if not normalized_name:
            raise ValueError(f"Invalid --expect value: {item!r}. Name cannot be empty.")
        try:
            expectations[normalized_name] = int(pages.strip())
        except ValueError as exc:
            raise ValueError(f"Invalid --expect value: {item!r}. PAGES must be an integer.") from exc
    return expectations


def resolve_budget(docx_path: Path, expectations: dict[str, int], default_budget: int) -> int:
    return expectations.get(docx_path.name, expectations.get(docx_path.stem, default_budget))


def parse_pdf_page_count(pdf_path: Path) -> int:
    result = subprocess.run(
        ["pdfinfo", str(pdf_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    match = PAGES_RE.search(result.stdout)
    if not match:
        raise RuntimeError(f"Could not parse page count from pdfinfo output for {pdf_path}")
    return int(match.group(1))


def render_documents(render_script: Path, outdir: Path, docx_paths: list[Path]) -> None:
    env = os.environ.copy()
    env["RENDER_OUTDIR"] = str(outdir)
    subprocess.run(
        [str(render_script), *[str(path) for path in docx_paths]],
        check=True,
        env=env,
    )


def verify_documents(
    outdir: Path,
    docx_paths: list[Path],
    expectations: dict[str, int],
    default_budget: int,
) -> dict[str, object]:
    results = []
    passed = True

    for docx_path in docx_paths:
        pdf_path = outdir / f"{docx_path.stem}.pdf"
        png_paths = sorted(outdir.glob(f"{docx_path.stem}-*.png"))
        budget = resolve_budget(docx_path, expectations, default_budget)

        if not pdf_path.exists():
            results.append(
                {
                    "input": str(docx_path),
                    "status": "failed",
                    "reason": f"Missing rendered PDF: {pdf_path}",
                    "page_budget": budget,
                }
            )
            passed = False
            continue

        try:
            page_count = parse_pdf_page_count(pdf_path)
        except Exception as exc:  # pragma: no cover - operational shelling only
            results.append(
                {
                    "input": str(docx_path),
                    "status": "failed",
                    "reason": str(exc),
                    "page_budget": budget,
                    "pdf_path": str(pdf_path),
                }
            )
            passed = False
            continue

        status = "passed"
        reason = ""
        if page_count > budget:
            status = "failed"
            reason = f"Page budget exceeded: {page_count} > {budget}"
            passed = False
        elif not png_paths:
            status = "failed"
            reason = "No PNG previews were produced."
            passed = False

        results.append(
            {
                "input": str(docx_path),
                "status": status,
                "reason": reason,
                "page_budget": budget,
                "page_count": page_count,
                "pdf_path": str(pdf_path),
                "png_paths": [str(path) for path in png_paths],
            }
        )

    return {
        "status": "passed" if passed else "failed",
        "outdir": str(outdir),
        "stdout_log": str(outdir / "soffice.stdout.log"),
        "stderr_log": str(outdir / "soffice.stderr.log"),
        "documents": results,
    }


def main() -> int:
    args = parse_args()
    try:
        expectations = parse_expectations(args.expect)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    render_script = Path(args.render_script).resolve()
    if not render_script.exists():
        print(f"Render script not found: {render_script}", file=sys.stderr)
        return 2

    docx_paths = [Path(path).resolve() for path in args.inputs]
    missing_inputs = [str(path) for path in docx_paths if not path.exists()]
    if missing_inputs:
        print("Missing input files:", file=sys.stderr)
        for path in missing_inputs:
            print(f"  - {path}", file=sys.stderr)
        return 2

    if args.outdir:
        outdir = Path(args.outdir).resolve()
        outdir.mkdir(parents=True, exist_ok=True)
    else:
        outdir = Path(tempfile.mkdtemp(prefix="docx-layout-check-"))

    try:
        render_documents(render_script, outdir, docx_paths)
        summary = verify_documents(outdir, docx_paths, expectations, args.default_page_budget)
    except subprocess.CalledProcessError as exc:
        failure = {
            "status": "failed",
            "outdir": str(outdir),
            "reason": f"Render pipeline failed with exit code {exc.returncode}",
            "command": exc.cmd,
        }
        if args.json:
            print(json.dumps(failure, indent=2))
        else:
            print("Layout verification failed before checks ran.")
            print(json.dumps(failure, indent=2))
        return 1

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Verification status: {summary['status']}")
        print(f"Rendered output: {summary['outdir']}")
        for result in summary["documents"]:
            label = Path(result["input"]).name
            if result["status"] == "passed":
                print(
                    f"  PASS {label}: {result['page_count']} page(s) within budget "
                    f"{result['page_budget']}"
                )
            else:
                print(f"  FAIL {label}: {result['reason']}")

    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
