#!/usr/bin/env python3
"""Extract location entities from Docling JSON using NuExtract2 and save CSV.

Example:
  uv run --project backend python backend/scripts/extract_locations_nuextract2.py \
    --input-json backend/output/sample.docling.json \
    --output-csv backend/output/sample.nuextract.locations.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

import torch
from docling_core.types.doc.document import DoclingDocument
from transformers import AutoModelForVision2Seq, AutoProcessor


DEFAULT_MODEL = "numind/NuExtract-2.0-2B"


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

    if isinstance(values, list):
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


def load_nuextract(model_name: str) -> tuple[Any, Any]:
    base_kwargs: dict[str, Any] = {
        "trust_remote_code": True,
        "device_map": "auto",
    }
    if torch.cuda.is_available():
        base_kwargs["torch_dtype"] = torch.bfloat16
        base_kwargs["attn_implementation"] = "flash_attention_2"

    try:
        model = AutoModelForVision2Seq.from_pretrained(model_name, **base_kwargs)
    except Exception:
        fallback = dict(base_kwargs)
        fallback.pop("attn_implementation", None)
        fallback.pop("torch_dtype", None)
        model = AutoModelForVision2Seq.from_pretrained(model_name, **fallback)

    processor = AutoProcessor.from_pretrained(
        model_name,
        trust_remote_code=True,
        padding_side="left",
        use_fast=True,
    )
    return model, processor


def extract_with_nuextract(text: str, model: Any, processor: Any, max_new_tokens: int) -> dict[str, Any]:
    template = json.dumps(
        {
            "locations": [
                {
                    "name": "verbatim-string",
                    "type": [
                        "city",
                        "country",
                        "river",
                        "oil field",
                        "region",
                        "state",
                        "province",
                        "port",
                        "sea",
                        "ocean",
                        "mountain",
                        "other",
                    ],
                    "evidence": "verbatim-string",
                }
            ]
        }
    )

    messages = [{"role": "user", "content": text}]
    prompt = processor.tokenizer.apply_chat_template(
        messages,
        template=template,
        tokenize=False,
        add_generation_prompt=True,
    )

    model_device = getattr(model, "device", torch.device("cpu"))
    inputs = processor(
        text=[prompt],
        images=None,
        padding=True,
        return_tensors="pt",
    )
    inputs = {k: v.to(model_device) for k, v in inputs.items()}

    generation_config = {
        "do_sample": False,
        "num_beams": 1,
        "max_new_tokens": max_new_tokens,
    }

    generated_ids = model.generate(**inputs, **generation_config)
    input_ids = inputs["input_ids"]
    trimmed = [out_ids[len(in_ids) :] for in_ids, out_ids in zip(input_ids, generated_ids)]
    output_text = processor.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)
    return parse_json_output(output_text[0] if output_text else "")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Load Docling JSON, run NuExtract2 extraction per element, write CSV."
    )
    parser.add_argument("--input-json", required=True, help="Path to Docling JSON file")
    parser.add_argument("--output-csv", default="", help="Output CSV path (default: alongside input)")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Hugging Face model id")
    parser.add_argument("--max-new-tokens", type=int, default=512, help="Generation cap for extraction")
    args = parser.parse_args()

    input_json = Path(args.input_json).expanduser().resolve()
    if not input_json.exists() or not input_json.is_file():
        raise SystemExit(f"Input JSON not found: {input_json}")

    if args.output_csv:
        output_csv = Path(args.output_csv).expanduser().resolve()
    else:
        output_csv = input_json.with_suffix("").with_suffix("")
        output_csv = output_csv.with_name(f"{output_csv.name}.nuextract.locations.csv")

    document = load_docling_document(input_json)
    model, processor = load_nuextract(args.model)

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

    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for idx, (item, level) in enumerate(document.iterate_items(with_groups=False, traverse_pictures=True)):
            element_text = extract_item_text(item, document)
            if not element_text:
                continue

            try:
                payload = extract_with_nuextract(element_text, model, processor, args.max_new_tokens)
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
