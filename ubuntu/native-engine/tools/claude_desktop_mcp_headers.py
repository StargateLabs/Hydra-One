"""Official Desktop headers-helper protocol; reads the existing shared hub token."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
token = (root / 'data/agent-harness/trueforge-mcp-token').read_text().strip()
print(json.dumps({'Authorization': 'Bearer ' + token}))
