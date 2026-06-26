#!/usr/bin/env python
"""Bundle plugin dependencies into dependencies/.

Run this with the same Python that QGIS uses, for example:
    path/to/qgis/python.exe bundle_deps.py

    & "C:\Program Files\QGIS 3.34.12\bin\python-qgis-ltr.bat" bundle_deps.py --git-exe "C:\Program Files\Git\cmd\git.exe"
"""

from __future__ import annotations


import argparse
import os
import subprocess
import sys
import json
import shutil


# You can specify versions/branches/commits in the following ways:
#   - "package==1.2.3" for a specific version
#   - "package @ git+https://github.com/user/repo@branch"
#   - "package @ git+https://github.com/user/repo@commit"
#   - Or just "package" for latest
DEFAULT_PACKAGES = [
    "pastastore @ git+https://github.com/pastas/pastastore@dev",
    "pastas @ git+https://github.com/pastas/pastas@dev",
    "pyqtgraph",
    "brodata==0.1.8",
    "hydropandas @ git+https://github.com/ArtesiaWater/hydropandas@96c55a6db0cbb22e643917aeadfc8e079a310328",
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


def run_pip_install(
    target_dir: str,
    packages: list[str],
    no_deps: bool,
    env: dict[str, str] | None = None,
) -> int:
    cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "--target", target_dir]
    if no_deps:
        cmd.append("--no-deps")
    cmd.extend(packages)
    return subprocess.call(cmd, env=env)


def build_install_env(packages: list[str], git_exe: str | None) -> dict[str, str]:
    env = os.environ.copy()
    needs_git = any("git+" in pkg for pkg in packages)
    if not needs_git:
        return env

    # Explicit override for environments (like QGIS launchers) with limited PATH.
    if git_exe:
        git_exe = os.path.abspath(git_exe)
        if not os.path.exists(git_exe):
            raise FileNotFoundError(f"Git executable not found: {git_exe}")
        git_dir = os.path.dirname(git_exe)
        env["PATH"] = git_dir + os.pathsep + env.get("PATH", "")
        return env

    # Auto-fallback for common Windows Git installation.
    if shutil.which("git", path=env.get("PATH", "")) is None:
        default_git = r"C:\Program Files\Git\cmd\git.exe"
        if os.path.exists(default_git):
            git_dir = os.path.dirname(default_git)
            env["PATH"] = git_dir + os.pathsep + env.get("PATH", "")

    return env


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
    parser.add_argument(
        "--git-exe",
        default=None,
        help="Optional: Full path to git executable for git+ package installs.",
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
    if args.git_exe:
        print("Git executable:", os.path.abspath(args.git_exe))

    try:
        install_env = build_install_env(packages, args.git_exe)
    except FileNotFoundError as e:
        print(str(e))
        return 2

    exit_code = run_pip_install(target_dir, packages, args.no_deps, env=install_env)
    if exit_code == 0:
        print("Done. Commit the dependencies/ folder with the plugin.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
