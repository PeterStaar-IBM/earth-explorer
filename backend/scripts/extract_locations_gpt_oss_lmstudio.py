#!/usr/bin/env python3
"""Extract location entities from Docling JSON using GPT-OSS via LM Studio API.

Example:
  uv run --project backend python backend/scripts/extract_locations_gpt_oss_lmstudio.py \
    --input-json backend/output/sample.docling.json \
    --output-csv backend/output/sample.gptoss.locations.csv \
    --model openai/gpt-oss-20b
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

import httpx
from docling_core.types.doc.document import DoclingDocument


DEFAULT_MODEL = "openai/gpt-oss-20b"
DEFAULT_BASE_URL = "http://127.0.0.1:1234/v1"


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
        page_no = getattr(prov[0], "page_no", None)
        if page_no is not None:
            return str(page_no)
    return ""


def parse_json_output(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return {}

    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}


def normalize_locations(payload: dict[str, Any]) -> list[dict[str, str]]:
    values = payload.get("locations")
    rows: list[dict[str, str]] = []
    if not isinstance(values, list):
        return rows

    for val in values:
        if isinstance(val, str):
            ent = val.strip()
            if ent:
                rows.append({"entity": ent, "entity_type": "location", "evidence": ""})
        elif isinstance(val, dict):
            ent = str(val.get("name", "")).strip()
            if ent:
                rows.append(
                    {
                        "entity": ent,
                        "entity_type": str(val.get("type", "location")).strip() or "location",
                        "evidence": str(val.get("evidence", "")).strip(),
                    }
                )

    return rows


def extract_with_lmstudio(
    text: str,
    client: httpx.Client,
    model: str,
    temperature: float,
    max_tokens: int,
) -> dict[str, Any]:
    schema = {
        "locations": [
            {
                "name": "string",
                "type": "city|country|river|oil field|region|state|province|port|sea|ocean|mountain|other",
                "evidence": "verbatim snippet from context",
            }
        ]
    }

    system_prompt = (
        "You extract geographical entities from text. "
        "Return strict JSON only. Do not include markdown fences or prose. "
        "If none found, return {\"locations\": []}."
    )

    user_prompt = (
        "Extract all location entities (cities, countries, rivers, oil fields, ports, regions, etc.) "
        "from the context below.\n"
        f"Output schema: {json.dumps(schema)}\n"
        f"Context:\n{text}"
    )

    response = client.post(
        "/chat/completions",
        json={
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        },
    )
    response.raise_for_status()
    payload = response.json()

    content = (
        payload.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    return parse_json_output(content)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load Docling JSON, run GPT-OSS via LM Studio extraction per element, write CSV."
    )
    parser.add_argument("--input-json", required=True, help="Path to Docling JSON file")
    parser.add_argument("--output-csv", default="", help="Output CSV path (default: alongside input)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="LM Studio loaded model identifier")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="LM Studio OpenAI-compatible base URL")
    parser.add_argument("--temperature", type=float, default=0.0, help="Sampling temperature")
    parser.add_argument("--max-tokens", type=int, default=400, help="Max output tokens")
    parser.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout seconds")
    args = parser.parse_args()

    input_json = Path(args.input_json).expanduser().resolve()
    if not input_json.exists() or not input_json.is_file():
        raise SystemExit(f"Input JSON not found: {input_json}")

    if args.output_csv:
        output_csv = Path(args.output_csv).expanduser().resolve()
    else:
        output_csv = input_json.with_suffix("").with_suffix("")
        output_csv = output_csv.with_name(f"{output_csv.name}.gptoss.locations.csv")

    document = load_docling_document(input_json)

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "element_index",
        "element_level",
        "element_class",
        "element_label",
        "page",
        "entity",
        "entity_type",
        "evidence",
        "model",
        "element_text",
    ]

    seen: set[tuple[str, str, str, str]] = set()
    rows_written = 0

    with httpx.Client(base_url=args.base_url, timeout=args.timeout) as client:
        # quick health check for clearer failures
        try:
            models_resp = client.get("/models")
            models_resp.raise_for_status()
        except Exception as exc:
            raise SystemExit(
                f"LM Studio endpoint is not reachable at {args.base_url}: {exc}"
            ) from exc

        with output_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()

            for idx, (item, level) in enumerate(document.iterate_items(with_groups=False, traverse_pictures=True)):
                element_text = extract_item_text(item, document)
                if not element_text:
                    continue

                try:
                    payload = extract_with_lmstudio(
                        text=element_text,
                        client=client,
                        model=args.model,
                        temperature=args.temperature,
                        max_tokens=args.max_tokens,
                    )
                except Exception:
                    continue

                for ent in normalize_locations(payload):
                    key = (str(idx), ent["entity"].lower(), ent["entity_type"].lower(), item_page(item))
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
                            "entity_type": ent["entity_type"],
                            "evidence": ent["evidence"],
                            "model": args.model,
                            "element_text": element_text,
                        }
                    )
                    rows_written += 1

    print(f"Wrote {rows_written} rows to {output_csv}")


if __name__ == "__main__":
    main()
