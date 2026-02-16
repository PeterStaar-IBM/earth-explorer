#!/usr/bin/env python3
"""Standalone PDF -> JSON processor using Docling.

Example:
  uv run --project backend python backend/scripts/process_pdf_docling.py \
    --input /path/to/file.pdf --output-dir backend/output
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _serialize_document(document: Any) -> dict[str, Any]:
    """Best-effort serialization across Docling versions."""
    if hasattr(document, "model_dump"):
        return document.model_dump()
    if hasattr(document, "dict"):
        return document.dict()
    if hasattr(document, "to_dict"):
        return document.to_dict()
    if hasattr(document, "export_to_dict"):
        return document.export_to_dict()
    raise RuntimeError("Unsupported Docling document object; no known dict serializer found.")


def _export_markdown(document: Any) -> str | None:
    if hasattr(document, "export_to_markdown"):
        return document.export_to_markdown()
    if hasattr(document, "to_markdown"):
        return document.to_markdown()
    return None


def process_pdf(input_pdf: Path, output_dir: Path) -> Path:
    try:
        from docling.document_converter import DocumentConverter
    except Exception as exc:
        raise RuntimeError(
            "Docling import failed. Install dependencies with `uv sync --project backend`."
        ) from exc

    converter = DocumentConverter()
    result = converter.convert(str(input_pdf))
    document = getattr(result, "document", result)

    doc_json = _serialize_document(document)
    markdown = _export_markdown(document)

    payload: dict[str, Any] = {
        "source_file": str(input_pdf.resolve()),
        "processed_at_utc": datetime.now(timezone.utc).isoformat(),
        "docling": {
            "result_type": type(result).__name__,
            "document_type": type(document).__name__,
        },
        "document": doc_json,
    }
    if markdown is not None:
        payload["markdown"] = markdown

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{input_pdf.stem}.docling.json"
    output_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return output_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Process a PDF with Docling and save JSON output.")
    parser.add_argument("--input", required=True, help="Path to input PDF file")
    parser.add_argument(
        "--output-dir",
        default="backend/output",
        help="Directory where JSON output will be written (default: backend/output)",
    )
    args = parser.parse_args()

    input_pdf = Path(args.input).expanduser().resolve()
    if not input_pdf.exists() or not input_pdf.is_file():
        raise SystemExit(f"Input file not found: {input_pdf}")
    if input_pdf.suffix.lower() != ".pdf":
        raise SystemExit(f"Input must be a PDF: {input_pdf}")

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_file = process_pdf(input_pdf, output_dir)
    print(f"Wrote Docling JSON: {output_file}")


if __name__ == "__main__":
    main()
