# -*- coding: utf-8 -*-
"""Tests for plugin structure and imports."""

import pytest
import os
from pathlib import Path


class TestPluginStructure:
    """Test the basic plugin structure and files."""

    def test_metadata_exists(self, plugin_dir):
        """Test that metadata.txt file exists."""
        metadata_path = Path(plugin_dir) / "metadata.txt"
        assert metadata_path.exists()

    def test_metadata_has_required_fields(self, plugin_dir):
        """Test that metadata.txt has required QGIS fields."""
        metadata_path = Path(plugin_dir) / "metadata.txt"
        content = metadata_path.read_text()
        
        required_fields = [
            "name=",
            "version=",
            "qgisMinimumVersion=",
            "description=",
            "author=",
        ]
        
        for field in required_fields:
            assert field in content, f"Missing required field: {field}"

    def test_readme_exists(self, plugin_dir):
        """Test that README.md file exists."""
        readme_path = Path(plugin_dir) / "README.md"
        assert readme_path.exists()

    def test_license_exists(self, plugin_dir):
        """Test that LICENSE.md file exists."""
        license_path = Path(plugin_dir) / "LICENSE.md"
        assert license_path.exists()

    def test_icon_exists(self, plugin_dir):
        """Test that icon.svg file exists."""
        icon_path = Path(plugin_dir) / "icon.svg"
        assert icon_path.exists()

    def test_main_module_exists(self, plugin_dir):
        """Test that main plugin module exists."""
        init_path = Path(plugin_dir) / "__init__.py"
        assert init_path.exists()

    def test_key_modules_exist(self, plugin_dir):
        """Test that key plugin modules exist."""
        key_files = [
            "pastastore_viewer.py",
            "main_dock.py",
            "plot_dock.py",
            "settings_dialog.py",
            "license_manager.py",
            "i18n_helper.py",
        ]
        
        for filename in key_files:
            filepath = Path(plugin_dir) / filename
            assert filepath.exists(), f"Missing key module: {filename}"

    def test_requirements_exists(self, plugin_dir):
        """Test that requirements.txt file exists."""
        requirements_path = Path(plugin_dir) / "requirements.txt"
        assert requirements_path.exists()

    def test_requirements_has_content(self, plugin_dir):
        """Test that requirements.txt has required packages."""
        requirements_path = Path(plugin_dir) / "requirements.txt"
        content = requirements_path.read_text()
        
        # Should have some dependencies
        assert len(content.strip()) > 0
        # Should mention at least one package
        assert "pastastore" in content or "pandas" in content or "numpy" in content


class TestPluginVersion:
    """Test plugin version parsing."""

    def test_version_format(self, plugin_dir):
        """Test that plugin version follows semantic versioning."""
        metadata_path = Path(plugin_dir) / "metadata.txt"
        content = metadata_path.read_text()
        
        for line in content.split("\n"):
            if line.strip().startswith("version="):
                version = line.split("=", 1)[1].strip()
                # Basic semver check: should have at least major.minor
                parts = version.split(".")
                assert len(parts) >= 2, f"Invalid version format: {version}"
                # Each part should be numeric or alphanumeric
                for part in parts:
                    assert len(part) > 0
                break
        else:
            pytest.fail("No version found in metadata.txt")

    def test_minimum_qgis_version(self, plugin_dir):
        """Test that minimum QGIS version is specified."""
        metadata_path = Path(plugin_dir) / "metadata.txt"
        content = metadata_path.read_text()
        
        assert "qgisMinimumVersion=" in content
        for line in content.split("\n"):
            if line.strip().startswith("qgisMinimumVersion="):
                version = line.split("=", 1)[1].strip()
                # Should be a version number
                assert len(version) > 0
                assert "." in version or version.isdigit()
                break
