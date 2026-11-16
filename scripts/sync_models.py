"""
Synchronize antigravity/config.yaml's default_model dropdown list with `agy models`.

Note: `agy models` requires an authenticated Google Account session, so this tool
is intended to be run locally (or inside the Home Assistant App container) whenever
Google Antigravity rolls out or deprecates models.

Usage:
  python3 scripts/sync_models.py           # Print diff without modifying config.yaml
  python3 scripts/sync_models.py --apply   # Update antigravity/config.yaml in place
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_YAML = REPO_ROOT / "antigravity" / "config.yaml"
MODEL_LINE_RE = re.compile(r"^([a-z0-9][a-z0-9._-]+)\s+.+$")
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\r")


def parse_agy_models_output(output: str) -> list[str]:
    """Extract ordered, deduplicated model IDs from `agy models` stdout."""
    cleaned = ANSI_ESCAPE_RE.sub("\n", output)
    models: list[str] = []
    seen: set[str] = set()
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = MODEL_LINE_RE.match(stripped)
        if match:
            model_id = match.group(1)
            if model_id not in seen:
                seen.add(model_id)
                models.append(model_id)
    return models


def fetch_live_models() -> list[str]:
    """Invoke `agy models` and return the parsed model IDs."""
    proc = subprocess.run(
        ["agy", "models"],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    combined = f"{proc.stdout}\n{proc.stderr}"
    if proc.returncode != 0 or "Please sign in" in combined:
        raise RuntimeError(f"Failed to query `agy models` (exit {proc.returncode}): {combined.strip()}")
    models = parse_agy_models_output(proc.stdout)
    if not models:
        raise RuntimeError(f"Could not parse any models from `agy models` output:\n{proc.stdout}")
    return models


def build_updated_config(config_text: str, live_models: list[str]) -> tuple[str, list[str], list[str]]:
    """Return updated config.yaml text plus (added, removed) model IDs."""
    default_match = re.search(r'^\s+default_model:\s*"([^"]+)"', config_text, re.MULTILINE)
    if default_match is None:
        raise ValueError("Missing options.default_model in antigravity/config.yaml")
    default_model = default_match.group(1)

    schema_match = re.search(r"^(\s+default_model:\s*)list\(([^)]+)\)", config_text, re.MULTILINE)
    if schema_match is None:
        raise ValueError("Missing schema.default_model list(...) in antigravity/config.yaml")

    current_models = schema_match.group(2).split("|")

    ordered = [default_model] if default_model in live_models else []
    for model_id in live_models:
        if model_id not in ordered:
            ordered.append(model_id)

    added = [m for m in ordered if m not in current_models]
    removed = [m for m in current_models if m not in ordered]

    new_line = f"{schema_match.group(1)}list({'|'.join(ordered)})"
    updated_text = config_text[: schema_match.start()] + new_line + config_text[schema_match.end() :]
    return updated_text, added, removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync config.yaml default_model list with `agy models`.")
    parser.add_argument("--apply", action="store_true", help="Write updated dropdown list to antigravity/config.yaml")
    args = parser.parse_args(argv)

    live_models = fetch_live_models()
    config_text = CONFIG_YAML.read_text(encoding="utf-8")
    updated_text, added, removed = build_updated_config(config_text, live_models)

    if not added and not removed:
        print(f"antigravity/config.yaml is already in sync ({len(live_models)} models).")
        return 0

    print(f"Added models  : {added or ['(none)']}")
    print(f"Removed models: {removed or ['(none)']}")

    if args.apply:
        CONFIG_YAML.write_text(updated_text, encoding="utf-8")
        print(f"Updated {CONFIG_YAML}.")
    else:
        print("Dry-run only. Re-run with --apply to update antigravity/config.yaml.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
