"""Shared browser/memory activation works with or without a live MCP hub."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from serve.shared_agent_services import activate_shared_service


def dashboard_file(root: Path) -> Path:
    path = root / "data" / "mcp-dashboard.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": {"browser": {
        "command": "node", "args": ["old-cli.js", "--config", "x"], "cwd": str(root)}}}), encoding="utf-8")
    return path


class SharedServiceTests(unittest.TestCase):
    def test_activation_without_an_mcp_hub_updates_config_and_selection(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = dashboard_file(root)
            updater = SimpleNamespace(root=root, activate=Mock())
            svc = SimpleNamespace(update_center=SimpleNamespace(harness_updates=updater), mcp=None)
            with patch("serve.shared_agent_services.selected", return_value={"binary": "new-cli.js"}):
                activate_shared_service(svc, "browser")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["mcpServers"]["browser"]["args"][0], "new-cli.js")
            updater.activate.assert_called_once_with("browser", rollback=False)

    def test_activation_replaces_an_existing_manager(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = dashboard_file(root)
            manager = Mock()
            hub = SimpleNamespace(servers={"browser": manager}, settings={})
            updater = SimpleNamespace(root=root, activate=Mock())
            svc = SimpleNamespace(update_center=SimpleNamespace(harness_updates=updater), mcp=hub)
            replacement = Mock()
            replacement.start.return_value = True
            with patch("serve.shared_agent_services.selected", return_value={"binary": "new-cli.js"}), \
                 patch("serve.mcp.McpServer", return_value=replacement):
                activate_shared_service(svc, "browser")
            manager.close.assert_called_once()
            self.assertIs(hub.servers["browser"], replacement)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["browser"]["args"][0],
                             "new-cli.js")


if __name__ == "__main__":
    unittest.main()
