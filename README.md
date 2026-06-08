# search_packages — Local GitHub Project Package Scanner

A Python CLI tool that walks a local directory tree of GitHub projects and reports which ones use a specific package, the exact file that declares it, and the version.

## Features

- 🔍 Scans **JS/TS** (`package.json`) and **Python** manifest files (`requirements*.txt`, `pyproject.toml`, `setup.py`, `setup.cfg`, `Pipfile`)
- 🤖 Scans **GitHub Actions workflows** (`.github/workflows/`) for `uses:` action references
- 📋 **Batch mode** via a YAML config file — scan multiple packages × locations in one run
- ⚡ **Concurrent** scanning via `ThreadPoolExecutor` (configurable thread count)
- 🗂️ Optional `--scan-code` flag to also search `import`/`require` statements in source files
- 🔒 **Never executes project code** — all parsing is purely static (regex + JSON/TOML/INI parsers)
- 🎨 Colour-formatted output via `rich`; falls back to plain text gracefully

---

## Requirements

- Python 3.8+
- Install dependencies:

```bash
pip install -r requirements.txt
```

Dependencies:
| Package | Purpose |
|---------|---------|
| `rich` | Console table output |
| `tomli` | TOML parsing on Python < 3.11 (stdlib `tomllib` used on ≥ 3.11) |
| `packaging` | Robust PEP 508 requirement parsing |
| `pyyaml` | YAML parsing for `--scan-config` batch mode |

---

## Usage

```
python search_packages.py <start_location> <package_name> [options]
python search_packages.py --scan-config <config_file> [options]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `START_LOCATION` | Root directory to walk from |
| `PACKAGE_NAME` | Package to search for (e.g. `requests`, `lodash`, `@scope/pkg`, `actions/checkout`) |

### Options

| Flag | Description |
|------|-------------|
| `--scan-config FILE` | Path to a YAML config file for batch scanning (replaces positional args) |
| `--scan-code` | Also scan source files for `import`/`require` statements (default: off) |
| `--threads N` | Number of worker threads (default: `2 × CPU count`, max 32) |
| `--no-color` | Disable Rich formatting; use plain text output |
| `-h`, `--help` | Show help message |

---

## Examples

```bash
# Search all projects under D:/git for the Python package "requests"
python search_packages.py D:/git requests

# Search for "lodash" and also scan JS/TS source files for import statements
python search_packages.py D:/git lodash --scan-code

# Use 16 threads for a large codebase
python search_packages.py D:/git requests --threads 16

# Plain output (no colour) — useful for piping or logging
python search_packages.py D:/git requests --no-color

# Search for a scoped npm package
python search_packages.py D:/git @angular/core --scan-code

# Search for a GitHub Actions action (any version)
python search_packages.py D:/git actions/checkout

# Search for a specific action version (exact ref match)
python search_packages.py D:/git actions/checkout@v4

# Batch scan: multiple packages × multiple locations from a config file
python search_packages.py --scan-config packages-to-be-scanned.yaml
```

---

## Batch Scanning (`--scan-config`)

For scanning multiple packages across multiple locations in one run, use a YAML config file:

```yaml
locations:
  - D:/git/my-projects
  - C:/work/repos

packages:
  - requests
  - lodash
  - actions/checkout

options:
  scan_code: true   # optional; overridden by --scan-code CLI flag
  threads: 16       # optional; overridden by --threads CLI flag
```

```bash
python search_packages.py --scan-config my-config.yaml
```

Each file in a project is read exactly once regardless of how many packages are being searched for. Results are printed as one table per package.

---

## Sample Output

```
Searching D:/git for requests …
Found 42 project root(s). Scanning with 16 thread(s) …

╭───────────────────────────────────────────────────────────────╮
│              Matches for requests                             │
├──────────────────┬──────────────────────────┬────────────────┤
│ Project          │ File                     │ Version        │
├──────────────────┼──────────────────────────┼────────────────┤
│ my-api           │ requirements.txt         │ >=2.28.0       │
│                  │ src/api/client.py        │ (imported)     │
│ data-pipeline    │ pyproject.toml           │ ^2.31.0        │
│ old-service      │ requirements-dev.txt     │ ==2.25.1       │
╰──────────────────┴──────────────────────────┴────────────────╯

Found 4 match(es) across 3 project(s).
```

---

## Supported Manifest Files

### JavaScript / TypeScript
| File | Fields checked |
|------|---------------|
| `package.json` | `dependencies`, `devDependencies`, `peerDependencies`, `optionalDependencies` |

### Python
| File | Fields checked |
|------|---------------|
| `requirements*.txt` | All non-comment lines |
| `pyproject.toml` | `[project] dependencies`, `[tool.poetry.*]` |
| `setup.py` | `install_requires`, `extras_require` (static regex, no execution) |
| `setup.cfg` | `[options] install_requires`, `[options.extras_require]` |
| `Pipfile` | `[packages]`, `[dev-packages]` |

### GitHub Actions
| File | Fields checked |
|------|---------------|
| `.github/workflows/*.yml` / `*.yaml` | All `uses:` step references |

Action references are matched case-insensitively. Include a `@ref` suffix in `PACKAGE_NAME` to pin to a specific version (e.g. `actions/checkout@v4`); omit it to match any version.

---

## Code Scanning (`--scan-code`)

When enabled, the tool also scans source files using **regular expressions only**. No project code is ever run.

### JS/TS source files (`*.js`, `*.ts`, `*.jsx`, `*.tsx`, `*.mjs`, `*.cjs`)
Detects:
- `require('pkg')`
- `import ... from 'pkg'`
- `import 'pkg'`
- `import('pkg')` (dynamic)
- `export ... from 'pkg'`

### Python source files (`*.py`, `*.pyi`)
Detects:
- `import pkg`
- `from pkg import ...`
- `from pkg.submodule import ...`

> **Note:** Python package names on PyPI often use hyphens (`my-package`) but are imported with underscores (`my_package`). The scanner normalises both automatically.

---

## Directories Skipped

The following directories are never visited:

`node_modules`, `.git`, `__pycache__`, `.venv`, `venv`, `dist`, `build`, `.tox`, `.mypy_cache`, `.next`, `.nuxt`, `out`, `.cache`, `.env`, `env`

---

## Architecture

```
search_packages.py        ← Entry point, CLI, ThreadPoolExecutor orchestration
lib/
  discovery.py            ← Walk directory tree, identify project roots
  manifest.py             ← Static parsers for all manifest file types
  workflow_scanner.py     ← Regex-based GitHub Actions `uses:` scanner
  code_scanner.py         ← Regex-based import/require scanner
  config.py               ← YAML config file loader and validator
  output.py               ← Rich (or plain) console table output
```
