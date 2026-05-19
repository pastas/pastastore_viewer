#!/usr/bin/env python
"""Bundle plugin dependencies into dependencies/.

Run this with the same Python that QGIS uses, for example:
    path/to/qgis/python.exe bundle_deps.py
"""

from __future__ import annotations


import argparse
import os
import subprocess
import sys
import json



# You can specify versions/branches/commits in the following ways:
#   - "package==1.2.3" for a specific version
#   - "package @ git+https://github.com/user/repo@branch"
#   - "package @ git+https://github.com/user/repo@commit"
#   - Or just "package" for latest
DEFAULT_PACKAGES = [
    "pastastore",
    "pastas",
    "pyqtgraph",
    "brodata",
    "hydropandas",
]


def ensure_pip_available() -> bool:
    try:
        import pip  # noqa: F401

        return True
    except Exception:
        print("pip is not available in this Python interpreter.")
        print("If this is QGIS Python, use OSGeo4W Setup to install python3-pip.")
        print("Then run this script from the OSGeo4W Shell.")
        print("Alternatively, try: python -m ensurepip --upgrade")
        return False


def run_pip_install(target_dir: str, packages: list[str], no_deps: bool) -> int:
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--target", target_dir]
    if no_deps:
        cmd.append("--no-deps")
    cmd.extend(packages)
    return subprocess.call(cmd)



def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bundle deps into dependencies/ for QGIS plugin."
    )
    parser.add_argument(
        "--target",
        default="dependencies",
        help="Target folder to place dependencies (default: dependencies)",
    )
    parser.add_argument(
        "--packages",
        nargs="+",
        default=DEFAULT_PACKAGES,
        help="Packages to install into the target folder.\n"
             "You can specify versions or git refs, e.g.:\n"
             "  pastas==1.13.2 hydropandas @ git+https://github.com/ArtesiaWater/hydropandas@main",
    )
    parser.add_argument(
        "--package-specs",
        default=None,
        help="Optional: Path to a JSON file with a list of package specs (overrides --packages).\n"
             "Each item can be a string (as above) or a dict with 'name' and 'spec'.",
    )
    parser.add_argument(
        "--no-deps",
        action="store_true",
        default=True,
        help="Do not install transitive dependencies (default: true)",
    )
    args = parser.parse_args()

    # Load package specs from JSON if provided
    packages = args.packages
    if args.package_specs:
        with open(args.package_specs, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        # Accept either a list of strings or a list of dicts with 'name' and 'spec'
        if isinstance(loaded, list):
            if all(isinstance(x, dict) and "spec" in x for x in loaded):
                packages = [x["spec"] for x in loaded]
            else:
                packages = loaded

    if not ensure_pip_available():
        return 2

    target_dir = os.path.abspath(args.target)
    os.makedirs(target_dir, exist_ok=True)

    print("Using Python:", sys.executable)
    print("Target folder:", target_dir)
    print("Packages:", ", ".join(packages))

    exit_code = run_pip_install(target_dir, packages, args.no_deps)
    if exit_code == 0:
        print("Done. Commit the dependencies/ folder with the plugin.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
