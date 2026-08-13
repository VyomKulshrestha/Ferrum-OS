#!/usr/bin/env python3
"""Run complete JSON Schema 2020-12 validation for public FerrumOS evidence."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    ("capabilities.json", "schemas/capabilities.schema.json"),
    ("benchmarks.json", "schemas/benchmarks.schema.json"),
)


def main() -> int:
    for document_name, schema_name in DOCUMENTS:
        document = json.loads((ROOT / document_name).read_text(encoding="utf-8"))
        schema = json.loads((ROOT / schema_name).read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema, format_checker=FormatChecker())
        errors = sorted(
            validator.iter_errors(document), key=lambda error: list(error.path)
        )
        if errors:
            details = "\n".join(
                f"- {'/'.join(map(str, error.path)) or '<root>'}: {error.message}"
                for error in errors
            )
            raise AssertionError(f"{document_name} failed {schema_name}:\n{details}")
        print(f"PASS  {document_name} validates against {schema_name}")
    print("\nFull public JSON Schema validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
