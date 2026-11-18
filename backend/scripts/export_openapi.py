"""Write the OpenAPI document to ``openapi.json``.

The document is committed so the frontend's generated types are reviewable in a diff,
and so CI can fail when the API changes without the types being regenerated.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("FMS_SECRET_KEY", "openapi-export-only-0123456789abcdef")
os.environ.setdefault("FMS_DATABASE_URL", "sqlite://")

from app.main import create_app

OUTPUT = Path(__file__).resolve().parents[1] / "openapi.json"


def main() -> int:
    document = create_app().openapi()
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != text:
            print(
                "openapi.json is out of date: run `python scripts/export_openapi.py` "
                "and regenerate the frontend types.",
                file=sys.stderr,
            )
            return 1
        print("openapi.json is up to date")
        return 0
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUTPUT} ({len(document.get('paths', {}))} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
