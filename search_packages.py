#!/usr/bin/env python3
"""
search_packages.py — Search GitHub project directories for a specific package.

Usage (single scan):
    python search_packages.py <start_location> <package_name> [options]

Usage (batch scan via config file):
    python search_packages.py --scan-config packages.yaml [options]

Examples:
    python search_packages.py D:/git requests
    python search_packages.py D:/git lodash --scan-code
    python search_packages.py D:/git requests --threads 16 --scan-code
    python search_packages.py --scan-config packages-to-be-scanned.yaml
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Ensure the repo root is on sys.path so `lib` is importable even when
# the script is invoked from a different working directory.
sys.path.insert(0, str(Path(__file__).parent))

from lib.discovery import find_project_roots
from lib.manifest import scan_manifests, scan_manifests_multi
from lib.output import ResultRow, print_results
from lib.workflow_scanner import scan_workflows, scan_workflows_multi

# code_scanner and config are imported lazily only when needed.


# ---------------------------------------------------------------------------
# Worker function (runs inside a thread)
# ---------------------------------------------------------------------------

def _scan_project(
    project_root: Path,
    package: str,
    scan_code: bool,
) -> list[ResultRow]:
    """Single-package scan — used by the positional-args mode."""
    return list(_scan_project_multi(project_root, [package], scan_code).get(package, []))


def _scan_project_multi(
    project_root: Path,
    packages: list[str],
    scan_code: bool,
) -> dict[str, list[ResultRow]]:
    """
    Scan a single project root for all *packages* in one pass.

    Each manifest / workflow / source file is read exactly once, then checked
    against every package.  Returns {package: [ResultRow, ...]} for all packages.
    """
    results: dict[str, list[ResultRow]] = {p: [] for p in packages}
    project_name = project_root.name

    def _add(pkg: str, file: Path, version: str) -> None:
        results[pkg].append(ResultRow(project_name, project_root, file, version))

    # 1. Manifest files (always)
    try:
        for pkg, matches in scan_manifests_multi(project_root, packages).items():
            for m in matches:
                _add(pkg, m.file, m.version)
    except Exception:
        _warn(f"Error scanning manifests in {project_root}: {traceback.format_exc()}")

    # 2. GitHub Actions workflows (always)
    try:
        for pkg, matches in scan_workflows_multi(project_root, packages).items():
            for m in matches:
                _add(pkg, m.file, m.version)
    except Exception:
        _warn(f"Error scanning workflows in {project_root}: {traceback.format_exc()}")

    # 3. Source code (only when --scan-code)
    if scan_code:
        try:
            from lib.code_scanner import scan_code_multi as _scan_code_multi

            for pkg, matches in _scan_code_multi(project_root, packages).items():
                for m in matches:
                    _add(pkg, m.file, m.version)
        except Exception:
            _warn(f"Error scanning source code in {project_root}: {traceback.format_exc()}")

    return results


def _warn(msg: str) -> None:
    print(f"[WARNING] {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Rich / plain helpers
# ---------------------------------------------------------------------------

def _print_info(msg: str, no_color: bool) -> None:
    if not no_color:
        try:
            from rich.console import Console
            Console().print(msg, highlight=False)
            return
        except ImportError:
            pass
    # Strip rich markup for plain output
    import re
    print(re.sub(r"\[/?[^\]]+\]", "", msg))


# ---------------------------------------------------------------------------
# Core scan for one (location, package) pair
# ---------------------------------------------------------------------------

def _scan_location(
    start: Path,
    package: str,
    scan_code: bool,
    threads: int,
    no_color: bool,
) -> list[ResultRow]:
    """Discover project roots under *start* and scan them for *package*."""
    _print_info(
        f"[bold]Searching[/bold] [cyan]{start}[/cyan] "
        f"for [bold cyan]{package}[/bold cyan] …",
        no_color,
    )

    roots = list(find_project_roots(start))
    if not roots:
        _print_info(f"[yellow]No project roots found under {start}.[/yellow]", no_color)
        return []

    _print_info(
        f"Found [green]{len(roots)}[/green] project root(s). "
        f"Scanning with [green]{threads}[/green] thread(s) …",
        no_color,
    )

    all_rows: list[ResultRow] = []
    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = {
            executor.submit(_scan_project, root, package, scan_code): root
            for root in roots
        }
        for future in as_completed(futures):
            root = futures[future]
            try:
                all_rows.extend(future.result())
            except Exception as exc:
                _warn(f"Unhandled error for {root}: {exc}")

    return all_rows


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="search_packages",
        description=(
            "Search a directory tree of GitHub projects for a given package.\n\n"
            "Single scan:\n"
            "  search_packages START_LOCATION PACKAGE_NAME [options]\n\n"
            "Batch scan from config file:\n"
            "  search_packages --scan-config FILE [options]\n\n"
            "Scans manifest files, GitHub Actions workflows, and optionally\n"
            "source files for import/require statements."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "start_location",
        metavar="START_LOCATION",
        nargs="?",
        help="Root directory to search from (required unless --scan-config is used).",
    )
    parser.add_argument(
        "package_name",
        metavar="PACKAGE_NAME",
        nargs="?",
        help=(
            "Package to search for, e.g. 'requests', 'lodash', 'actions/checkout' "
            "(required unless --scan-config is used)."
        ),
    )
    parser.add_argument(
        "--scan-config",
        metavar="FILE",
        help=(
            "Path to a YAML config file with 'locations' and 'packages' lists. "
            "Runs all package × location combinations in one pass."
        ),
    )
    parser.add_argument(
        "--scan-code",
        action="store_true",
        default=False,
        help=(
            "Also scan source files (.js, .ts, .py, …) for import/require "
            "statements. Off by default. No project code is executed."
        ),
    )
    parser.add_argument(
        "--threads",
        metavar="N",
        type=int,
        default=min(32, (os.cpu_count() or 4) * 2),
        help="Number of worker threads (default: 2 × CPU count, max 32).",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable colour/rich formatting in the output.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    threads = max(1, args.threads)

    # ------------------------------------------------------------------
    # Determine mode: config file  vs.  positional args
    # ------------------------------------------------------------------

    if args.scan_config:
        return _run_config_mode(args, threads)

    # Positional mode — both args are required
    if not args.start_location or not args.package_name:
        parser.error(
            "START_LOCATION and PACKAGE_NAME are required unless --scan-config is used."
        )

    start = Path(args.start_location)
    if not start.exists() or not start.is_dir():
        print(f"Error: '{start}' is not an existing directory.", file=sys.stderr)
        return 1

    rows = _scan_location(start, args.package_name, args.scan_code, threads, args.no_color)
    print_results(rows, args.package_name, no_color=args.no_color)
    return 0


def _run_config_mode(args: argparse.Namespace, threads: int) -> int:
    """
    Load the YAML config and scan all locations for all packages.

    Loop order: location → project roots (concurrent) → scan all packages per root.
    Each file in a project is read exactly once regardless of how many packages
    are being searched for.
    """
    from lib.config import ConfigError, load_config

    try:
        config = load_config(args.scan_config)
    except (ConfigError, ImportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # CLI flags override config-file options when explicitly provided
    scan_code = args.scan_code
    if config.options.scan_code is not None and not args.scan_code:
        scan_code = config.options.scan_code
    if config.options.threads is not None and args.threads == min(32, (os.cpu_count() or 4) * 2):
        threads = config.options.threads

    _print_info(
        f"[bold]Config:[/bold] [green]{len(config.packages)}[/green] package(s) × "
        f"[green]{len(config.locations)}[/green] location(s)",
        args.no_color,
    )

    # Accumulate results per package across all locations
    all_results: dict[str, list[ResultRow]] = {p: [] for p in config.packages}
    overall_rc = 0

    for location_str in config.locations:
        start = Path(location_str)
        if not start.exists() or not start.is_dir():
            _warn(f"Skipping invalid location: {location_str}")
            overall_rc = 1
            continue

        _print_info(
            f"[bold]Searching[/bold] [cyan]{start}[/cyan] "
            f"({len(config.packages)} packages) …",
            args.no_color,
        )

        roots = list(find_project_roots(start))
        if not roots:
            _print_info(f"[yellow]No project roots found under {start}.[/yellow]", args.no_color)
            continue

        _print_info(
            f"Found [green]{len(roots)}[/green] project root(s). "
            f"Scanning with [green]{threads}[/green] thread(s) …",
            args.no_color,
        )

        # Each thread scans one project root for ALL packages at once
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = {
                executor.submit(
                    _scan_project_multi, root, config.packages, scan_code
                ): root
                for root in roots
            }
            for future in as_completed(futures):
                root = futures[future]
                try:
                    per_pkg = future.result()
                    for pkg, rows in per_pkg.items():
                        all_results[pkg].extend(rows)
                except Exception as exc:
                    _warn(f"Unhandled error for {root}: {exc}")

    # Print one table per package, in config order
    for package in config.packages:
        print_results(all_results[package], package, no_color=args.no_color)

    return overall_rc


if __name__ == "__main__":
    sys.exit(main())

