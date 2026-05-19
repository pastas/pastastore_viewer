#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Test runner script for Pastastore Viewer plugin.

Usage:
    python run_tests.py                    # Run all unit tests
    python run_tests.py --all              # Run all tests
    python run_tests.py --coverage         # Run with coverage report
    python run_tests.py --parallel         # Run tests in parallel
    python run_tests.py --file test_name   # Run specific test file
    python run_tests.py --help             # Show help
"""

import sys
import subprocess
import argparse
from pathlib import Path


def run_command(cmd):
    """Run a shell command and return exit code."""
    print(f"Running: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(Path(__file__).parent.parent))


def main():
    parser = argparse.ArgumentParser(
        description="Test runner for Pastastore Viewer plugin"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all tests including integration tests",
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Generate coverage report",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Run tests in parallel",
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Run specific test file",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=1,
        help="Increase verbosity (-v, -vv, -vvv)",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Skip slow tests",
    )
    
    args = parser.parse_args()
    
    # Build pytest command
    cmd = ["pytest", "tests/"]
    
    # Add test selection
    if not args.all:
        cmd.extend(["-m", "unit"])
    
    if args.fast:
        cmd.extend(["-m", "not slow"])
    
    if args.file:
        cmd[-1] = f"tests/{args.file}"
    
    # Add verbosity
    cmd.append("-" + "v" * args.verbose)
    
    # Add coverage
    if args.coverage:
        cmd.extend([
            "--cov=.",
            "--cov-report=html",
            "--cov-report=term",
        ])
    
    # Add parallel execution
    if args.parallel:
        cmd.extend(["-n", "auto"])
    
    # Run tests
    result = run_command(cmd)
    
    if result.returncode == 0:
        print("\n✓ All tests passed!")
    else:
        print(f"\n✗ Tests failed with exit code {result.returncode}")
    
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
