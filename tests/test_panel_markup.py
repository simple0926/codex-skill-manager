from pathlib import Path
import unittest


ROOT = Path(__file__).parents[1]


class PanelMarkupTests(unittest.TestCase):
    def test_table_first_workspace_has_required_controls(self) -> None:
        html = (ROOT / "panel" / "static" / "index.html").read_text(encoding="utf-8")

        for marker in (
            'id="globalSearch"',
            'id="statusTabs"',
            'id="healthFilter"',
            'id="skillRows"',
            'id="detailInspector"',
            'id="inspectorContent"',
        ):
            self.assertIn(marker, html)
        self.assertNotIn('class="hero-row"', html)
        self.assertNotIn('id="scopeFilter"', html)
        self.assertNotIn('id="includePlugins"', html)
        self.assertNotIn("<th>来源</th>", html)
        self.assertNotIn('id="discoverView"', html)
        self.assertNotIn('id="discoverButton"', html)
        self.assertIn("只显示可更新或可安全卸载的 Skills", html)

    def test_panel_script_supports_status_views_and_keyboard_selection(self) -> None:
        script = (ROOT / "panel" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn("function skillStatus", script)
        self.assertIn("function selectSkill", script)
        self.assertIn('event.key === "ArrowDown"', script)
        self.assertIn('event.key === "ArrowUp"', script)

    def test_panel_loads_local_inventory_before_background_metadata(self) -> None:
        script = (ROOT / "panel" / "static" / "app.js").read_text(encoding="utf-8")

        self.assertIn('await loadInventory("local")', script)
        self.assertIn('loadInventory("missing")', script)
        self.assertIn("function compactWarning", script)
        self.assertNotIn('hidden_system_count', script)
        self.assertNotIn("function loadDiscovery", script)
        self.assertNotIn('beginAction("install"', script)


if __name__ == "__main__":
    unittest.main()
