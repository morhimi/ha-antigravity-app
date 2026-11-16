# Antigravity Home Assistant App (`ha-antigravity-app`) Workspace Rules

## 1. Mandatory Documentation & Metadata Sync on Every Change
Never bump a version, rename the App, or add/change configuration options, REST API parameters, or persistence paths without updating **all** user-facing documentation in the same commit:
1. [antigravity/config.yaml](file:///Users/mor/projects/home_assistant/ha-antigravity-app/antigravity/config.yaml): Update `version`, `name`, `options`, and `schema` (omitting keys set to Home Assistant App schema defaults).
2. [antigravity/translations/en.yaml](file:///Users/mor/projects/home_assistant/ha-antigravity-app/antigravity/translations/en.yaml): Add/update UI names and descriptions for every `config.yaml` option.
3. [antigravity/DOCS.md](file:///Users/mor/projects/home_assistant/ha-antigravity-app/antigravity/DOCS.md): Document every config option, `/data` persistence symlink, `/health` behavior, and keep the `rest_command.antigravity_generate` YAML payload template synchronized with all supported `POST /api/generate` parameters.
4. [antigravity/README.md](file:///Users/mor/projects/home_assistant/ha-antigravity-app/antigravity/README.md) & root [README.md](file:///Users/mor/projects/home_assistant/ha-antigravity-app/README.md): Keep the App display name (`name:` in `config.yaml`), feature summaries, model catalog examples, `rest_command.antigravity_generate` example, and Blueprint link aligned.
5. [antigravity/CHANGELOG.md](file:///Users/mor/projects/home_assistant/ha-antigravity-app/antigravity/CHANGELOG.md): Prepend a `## <version>` entry matching `config.yaml`.

## 2. Pre-Push Validation Gate
Before pushing any commit to `main`:
1. Run `python3 -m unittest discover -s tests -v` (executes both REST API tests in [tests/test_agy_api.py](file:///Users/mor/projects/home_assistant/ha-antigravity-app/tests/test_agy_api.py) and doc-consistency checks in [tests/test_docs_sync.py](file:///Users/mor/projects/home_assistant/ha-antigravity-app/tests/test_docs_sync.py)).
2. Keep `.github/workflows/*.yaml` lines <= 120 characters for zero-warning `yamllint` runs and ensure Python changes comply with `ruff check`.
