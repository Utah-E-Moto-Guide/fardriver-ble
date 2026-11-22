import json
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class PluginManifestTest(unittest.TestCase):
    def setUp(self):
        self.project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        self.plugin = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))

    def test_versions_match(self):
        self.assertEqual(self.plugin["version"], self.project["version"])

    def test_marketplace_lists_this_plugin(self):
        m = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
        self.assertIn({"name": self.plugin["name"], "source": "./"},
                      [{k: p[k] for k in ("name", "source")} for p in m["plugins"]])

    def test_mcp_server_runs_a_real_entry_point(self):
        server = self.plugin["mcpServers"]["fardriver"]
        self.assertEqual(server["command"], "uv")
        self.assertIn("${CLAUDE_PLUGIN_ROOT}", server["args"])
        self.assertIn(server["args"][-1], self.project["scripts"])

    def test_no_project_mcp_file(self):
        # A root .mcp.json would also load as a project MCP config for anyone working in a clone,
        # where ${CLAUDE_PLUGIN_ROOT} does not resolve. The server lives in plugin.json instead.
        self.assertFalse((ROOT / ".mcp.json").exists())

    def test_skill_ships(self):
        self.assertTrue((ROOT / "skills/fardriver-tune/SKILL.md").exists())


if __name__ == "__main__":
    unittest.main()
