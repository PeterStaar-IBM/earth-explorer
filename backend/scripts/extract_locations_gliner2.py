#!/usr/bin/env python3
"""Extract location entities from Docling JSON using GLiNER2 and save CSV.

Example:
  uv run --project backend python backend/scripts/extract_locations_gliner2.py \
    --input-json backend/output/sample.docling.json \
    --output-csv backend/output/sample.locations.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from docling_core.types.doc.document import DoclingDocument


DEFAULT_LABELS = [
    "location",
    "city",
    "country",
    "region",
    "state",
    "province",
    "river",
    "lake",
    "ocean",
    "sea",
    "mountain",
    "oil field",
    "oilfield",
    "port",
]


def load_docling_document(input_json: Path) -> DoclingDocument:
    data = json.loads(input_json.read_text(encoding="utf-8"))
    doc_payload = data.get("document") if isinstance(data, dict) else None
    if doc_payload is None:
        doc_payload = data

    if isinstance(doc_payload, str):
        return DoclingDocument.model_validate_json(doc_payload)
    return DoclingDocument.model_validate(doc_payload)


def extract_item_text(item: Any, document: DoclingDocument) -> str:
    text = getattr(item, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()

    if hasattr(item, "caption_text"):
        try:
            caption = item.caption_text(document)
            if isinstance(caption, str) and caption.strip():
                return caption.strip()
        except Exception:
            pass

    return ""


def item_page(item: Any) -> str:
    prov = getattr(item, "prov", None)
    if isinstance(prov, list) and prov:
        first = prov[0]
        page_no = getattr(first, "page_no", None)
        if page_no is not None:
            return str(page_no)
    return ""


def run_gliner2(text: str, model: Any, labels: list[str], threshold: float) -> dict[str, Any]:
    try:
        return model.extract_entities(text, labels, threshold=threshold)
    except TypeError:
        return model.extract_entities(text, labels)


def iter_entities(result: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    if isinstance(result, dict) and isinstance(result.get("entities"), dict):
        for label, values in result["entities"].items():
            if isinstance(values, list):
                for value in values:
                    if isinstance(value, dict):
                        rows.append(
                            {
                                "entity": str(value.get("text", "")).strip(),
                                "entity_label": str(label),
                                "start": value.get("start", ""),
                                "end": value.get("end", ""),
                                "score": value.get("score", ""),
                            }
                        )
                    elif value is not None:
                        rows.append(
                            {
                                "entity": str(value).strip(),
                                "entity_label": str(label),
                                "start": "",
                                "end": "",
                                "score": "",
                            }
                        )
        return [r for r in rows if r["entity"]]

    if isinstance(result, list):
        for value in result:
            if isinstance(value, dict):
                rows.append(
                    {
                        "entity": str(value.get("text", "")).strip(),
                        "entity_label": str(value.get("label", value.get("type", "location"))),
                        "start": value.get("start", ""),
                        "end": value.get("end", ""),
                        "score": value.get("score", ""),
                    }
                )
        return [r for r in rows if r["entity"]]

    return []


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load Docling JSON, run GLiNER2 location extraction on elements, write CSV."
    )
    parser.add_argument("--input-json", required=True, help="Path to Docling JSON file")
    parser.add_argument("--output-csv", default="", help="Output CSV path (default: alongside input)")
    parser.add_argument("--model", default="fastino/gliner2-base-v1", help="HF model id")
    parser.add_argument(
        "--labels",
        nargs="+",
        default=DEFAULT_LABELS,
        help="Entity labels/schema for GLiNER2 extraction",
    )
    parser.add_argument("--threshold", type=float, default=0.35, help="Optional extraction threshold")
    args = parser.parse_args()

    input_json = Path(args.input_json).expanduser().resolve()
    if not input_json.exists() or not input_json.is_file():
        raise SystemExit(f"Input JSON not found: {input_json}")

    if args.output_csv:
        output_csv = Path(args.output_csv).expanduser().resolve()
    else:
        output_csv = input_json.with_suffix("").with_suffix("")
        output_csv = output_csv.with_name(f"{output_csv.name}.locations.csv")

    try:
        from gliner2 import GLiNER2
    except Exception as exc:
        raise SystemExit(
            "GLiNER2 import failed. Run `uv sync --project backend` to install dependencies."
        ) from exc

    document = load_docling_document(input_json)
    model = GLiNER2.from_pretrained(args.model)

    output_csv.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "element_index",
        "element_level",
        "element_class",
        "element_label",
        "page",
        "entity",
        "entity_label",
        "start",
        "end",
        "score",
        "element_text",
    ]

    seen: set[tuple[str, str, str, str]] = set()
    rows_written = 0

    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for idx, (item, level) in enumerate(document.iterate_items(with_groups=False, traverse_pictures=True)):
            element_text = extract_item_text(item, document)
            if not element_text:
                continue

            prediction = run_gliner2(element_text, model, args.labels, args.threshold)
            entities = iter_entities(prediction)

            for ent in entities:
                key = (
                    str(idx),
                    ent["entity"].lower(),
                    ent["entity_label"].lower(),
                    str(item_page(item)),
                )
                if key in seen:
                    continue
                seen.add(key)

                writer.writerow(
                    {
                        "element_index": idx,
                        "element_level": level,
                        "element_class": type(item).__name__,
                        "element_label": str(getattr(item, "label", "")),
                        "page": item_page(item),
                        "entity": ent["entity"],
                        "entity_label": ent["entity_label"],
                        "start": ent["start"],
                        "end": ent["end"],
                        "score": ent["score"],
                        "element_text": element_text,
                    }
                )
                rows_written += 1

    print(f"Wrote {rows_written} rows to {output_csv}")


if __name__ == "__main__":
    main()
