# -*- coding: utf-8 -*-
"""Pytest configuration and shared fixtures."""

import os
import sys
import pytest
import tempfile
from pathlib import Path

# Add parent directory to path to import plugin modules
PLUGIN_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PLUGIN_DIR))


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def plugin_dir():
    """Return the plugin directory path."""
    return str(PLUGIN_DIR)


@pytest.fixture
def license_dir(temp_dir):
    """Create a temporary license directory."""
    license_path = Path(temp_dir) / "license"
    license_path.mkdir()
    return str(license_path)
