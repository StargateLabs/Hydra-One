"""Compile official prompt data into an offline, lazily loaded catalog."""
import csv, hashlib, io, json
from datetime import datetime, timezone
from pathlib import Path

def compile_catalog(raw):
    csv.field_size_limit(32 * 1024**2)
    rows = []
    for i, row in enumerate(csv.DictReader(io.StringIO(raw.decode("utf-8-sig")))):
        if not row.get("act", "").strip() or not row.get("prompt", "").strip():
            raise ValueError(f"Invalid catalog row {i + 1}")
        rows.append({"id": str(i), "title": row["act"], "text": row["prompt"],
                     "developer": row.get("for_devs") == "TRUE", "type": row.get("type", "TEXT"),
                     "contributor": row.get("contributor", "")})
    return {"source": "https://github.com/f/prompts.chat", "license": "CC0 1.0",
            "sha256": hashlib.sha256(raw).hexdigest(), "importedAt": datetime.now(timezone.utc).isoformat(), "items": rows}

if __name__ == "__main__":
    catalog = compile_catalog(Path("output/prompts-chat.csv").read_bytes())
    Path("serve/web/prompt-catalog-data.js").write_text(
        "window.StrataPromptCatalog=" + json.dumps(catalog, ensure_ascii=True) + ";\n", encoding="utf-8")
    print(f"Imported {len(catalog['items'])} prompts")
