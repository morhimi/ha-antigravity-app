"""
Documentation and configuration consistency checks for ha-antigravity-app.
Ensures config.yaml, translations, DOCS.md, READMEs, CHANGELOG.md,
the Blueprint, and agy-api-server.py stay synchronized across releases.
"""

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = REPO_ROOT / "antigravity"
CONFIG_YAML = APP_DIR / "config.yaml"
TRANSLATIONS_EN = APP_DIR / "translations" / "en.yaml"
DOCS_MD = APP_DIR / "DOCS.md"
APP_README = APP_DIR / "README.md"
ROOT_README = REPO_ROOT / "README.md"
CHANGELOG_MD = APP_DIR / "CHANGELOG.md"
API_SERVER = APP_DIR / "rootfs" / "usr" / "local" / "bin" / "agy-api-server.py"
BLUEPRINT = REPO_ROOT / "blueprints" / "automation" / "antigravity_camera_vision.yaml"


def _extract_top_level_block_keys(yaml_text: str, section_name: str) -> set[str]:
    keys: set[str] = set()
    in_section = False
    for line in yaml_text.splitlines():
        if re.match(rf"^{re.escape(section_name)}:\s*$", line):
            in_section = True
            continue
        if in_section:
            if line and not line.startswith(" ") and not line.startswith("#"):
                break
            match = re.match(r"^  ([a-z0-9_]+):", line)
            if match:
                keys.add(match.group(1))
    return keys


class TestDocsSync(unittest.TestCase):
    def setUp(self) -> None:
        self.config_text = CONFIG_YAML.read_text(encoding="utf-8")
        self.translations_text = TRANSLATIONS_EN.read_text(encoding="utf-8")
        self.docs_text = DOCS_MD.read_text(encoding="utf-8")
        self.app_readme_text = APP_README.read_text(encoding="utf-8")
        self.root_readme_text = ROOT_README.read_text(encoding="utf-8")
        self.changelog_text = CHANGELOG_MD.read_text(encoding="utf-8")
        self.api_server_text = API_SERVER.read_text(encoding="utf-8")
        self.blueprint_text = BLUEPRINT.read_text(encoding="utf-8")

    def test_config_options_documented_and_translated(self) -> None:
        option_keys = _extract_top_level_block_keys(self.config_text, "options")
        schema_keys = _extract_top_level_block_keys(self.config_text, "schema")
        translated_keys = _extract_top_level_block_keys(self.translations_text, "configuration")

        self.assertTrue(option_keys, "Expected non-empty options in config.yaml")
        self.assertTrue(option_keys.issubset(schema_keys), f"Options missing from schema: {option_keys - schema_keys}")

        for key in sorted(schema_keys):
            self.assertIn(key, translated_keys, f"Option '{key}' missing from translations/en.yaml")
            self.assertIn(f"`{key}`", self.docs_text, f"Option '{key}' missing from antigravity/DOCS.md")

    def test_app_display_name_synced_across_docs(self) -> None:
        name_match = re.search(r"^name:\s*(.+)$", self.config_text, re.MULTILINE)
        if name_match is None:
            self.fail("Missing 'name' in antigravity/config.yaml")
        app_name = name_match.group(1).strip().strip('"').strip("'")

        for path_label, text in [
            ("antigravity/DOCS.md", self.docs_text),
            ("antigravity/README.md", self.app_readme_text),
            ("README.md", self.root_readme_text),
        ]:
            self.assertIn(app_name, text, f"App name '{app_name}' missing from {path_label}")
            self.assertNotIn(
                "# Home Assistant App: Antigravity CLI",
                text,
                f"Stale heading found in {path_label}",
            )

    def test_version_has_changelog_entry(self) -> None:
        ver_match = re.search(r'^version:\s*"([^"]+)"', self.config_text, re.MULTILINE)
        if ver_match is None:
            self.fail("Missing 'version' in antigravity/config.yaml")
        version = ver_match.group(1)
        self.assertRegex(self.changelog_text, rf"(?m)^## {re.escape(version)}\s*$")

    def test_defaults_and_rest_command_params_synced(self) -> None:
        model_match = re.search(r'^\s+default_model:\s*"([^"]+)"', self.config_text, re.MULTILINE)
        timeout_match = re.search(r"^\s+default_timeout:\s*(\d+)", self.config_text, re.MULTILINE)
        if model_match is None or timeout_match is None:
            self.fail("Missing default_model or default_timeout in antigravity/config.yaml")

        default_model = model_match.group(1)
        default_timeout = timeout_match.group(1)

        self.assertIn(f'os.environ.get("AGY_DEFAULT_MODEL", "{default_model}")', self.api_server_text)
        self.assertIn(f'os.environ.get("AGY_DEFAULT_TIMEOUT", "{default_timeout}")', self.api_server_text)
        self.assertIn(default_model, self.docs_text)
        self.assertIn(default_model, self.app_readme_text)
        self.assertIn(default_model, self.root_readme_text)
        self.assertIn(default_timeout, self.docs_text)

        for param in ("json_schema", "conversation_id", "async", "event_type"):
            self.assertIn(f'"{param}"', self.docs_text, f"rest_command param '{param}' missing from DOCS.md")
            self.assertIn(f'"{param}"', self.root_readme_text, f"rest_command param '{param}' missing from README.md")

    def test_rest_command_name_matches_blueprint(self) -> None:
        self.assertIn("antigravity_generate:", self.docs_text)
        self.assertIn("antigravity_generate:", self.root_readme_text)
        self.assertIn("action: rest_command.antigravity_generate", self.blueprint_text)
        self.assertNotIn("antigravity_vision:", self.docs_text)


if __name__ == "__main__":
    unittest.main()
