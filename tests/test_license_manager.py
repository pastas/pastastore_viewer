# -*- coding: utf-8 -*-
"""Tests for the license manager module."""

import json
import pytest
from pathlib import Path
from license_manager import (
    LicenseManager,
    LicenseState,
    FEATURE_PRO,
    FEATURE_PRONL,
    _normalize_base_url,
    _machine_id,
)


class TestLicenseState:
    """Test the LicenseState dataclass."""

    def test_default_state(self):
        """Test default LicenseState initialization."""
        state = LicenseState()
        assert not state.valid
        assert state.reason == "No license"
        assert state.license_type == "free"
        assert state.features == ()
        assert state.expires_at is None
        assert state.customer_name is None

    def test_custom_state(self):
        """Test LicenseState with custom values."""
        features = (FEATURE_PRO, FEATURE_PRONL)
        state = LicenseState(
            valid=True,
            reason="Valid",
            license_type="pro",
            features=features,
            expires_at="2025-12-31",
            customer_name="Test Customer",
        )
        assert state.valid
        assert state.license_type == "pro"
        assert state.features == features
        assert state.customer_name == "Test Customer"


class TestNormalizeBaseUrl:
    """Test URL normalization utility."""

    def test_normalize_removes_trailing_slash(self):
        """Test that trailing slashes are removed."""
        assert _normalize_base_url("https://example.com/") == "https://example.com"

    def test_normalize_preserves_base_url(self):
        """Test that base URL structure is preserved."""
        assert _normalize_base_url("https://example.com") == "https://example.com"

    def test_normalize_handles_whitespace(self):
        """Test that leading/trailing whitespace is stripped."""
        assert _normalize_base_url("  https://example.com/  ") == "https://example.com"

    def test_normalize_handles_multiple_slashes(self):
        """Test that multiple trailing slashes are removed."""
        assert _normalize_base_url("https://example.com///") == "https://example.com"


class TestMachineId:
    """Test machine ID generation."""

    def test_machine_id_returns_string(self):
        """Test that machine_id returns a string."""
        mid = _machine_id()
        assert isinstance(mid, str)

    def test_machine_id_is_hex(self):
        """Test that machine_id is valid hexadecimal."""
        mid = _machine_id()
        # Should be a valid hex string
        int(mid, 16)

    def test_machine_id_is_consistent(self):
        """Test that machine_id is consistent across calls."""
        mid1 = _machine_id()
        mid2 = _machine_id()
        assert mid1 == mid2

    def test_machine_id_length(self):
        """Test that machine_id has expected length (SHA256 hex)."""
        mid = _machine_id()
        # SHA256 hex should be 64 characters
        assert len(mid) == 64


class TestLicenseManager:
    """Test the LicenseManager class."""

    def test_initialization(self, temp_dir):
        """Test LicenseManager initialization."""
        lm = LicenseManager(temp_dir, "0.1")
        assert lm.plugin_dir == Path(temp_dir)
        assert lm.plugin_version == "0.1"
        assert lm.license_dir.exists()
        assert not lm.has_feature(FEATURE_PRO)
        assert not lm.has_feature(FEATURE_PRONL)

    def test_machine_id_property(self, temp_dir):
        """Test machine_id property."""
        lm = LicenseManager(temp_dir, "0.1")
        mid = lm.machine_id
        assert isinstance(mid, str)
        assert len(mid) == 64

    def test_status_text_no_license(self, temp_dir):
        """Test status_text when no license is loaded."""
        lm = LicenseManager(temp_dir, "0.1")
        status = lm.status_text()
        assert "Free" in status
        assert "No license" in status

    def test_status_text_with_valid_license(self, temp_dir):
        """Test status_text with a valid license state."""
        lm = LicenseManager(temp_dir, "0.1")
        lm.state = LicenseState(
            valid=True,
            license_type="pro",
            customer_name="Test User",
            expires_at="2025-12-31",
        )
        lm._session_validated = True
        status = lm.status_text()
        assert "pro" in status
        assert "Test User" in status
        assert "2025-12-31" in status

    def test_has_feature_requires_session_validation(self, temp_dir):
        """Test that has_feature requires session validation."""
        lm = LicenseManager(temp_dir, "0.1")
        lm.state = LicenseState(
            valid=True,
            features=(FEATURE_PRO,),
        )
        # Not validated in session yet
        assert not lm.has_feature(FEATURE_PRO)
        # After validation
        lm._session_validated = True
        assert lm.has_feature(FEATURE_PRO)

    def test_has_feature_pro_includes_pronl(self, temp_dir):
        """Test that checking for PRO includes ProNL."""
        lm = LicenseManager(temp_dir, "0.1")
        lm.state = LicenseState(
            valid=True,
            features=(FEATURE_PRONL,),
        )
        lm._session_validated = True
        assert lm.has_feature(FEATURE_PRO)
        assert lm.has_feature(FEATURE_PRONL)

    def test_deactivate_removes_license(self, temp_dir):
        """Test that deactivate removes the license file."""
        lm = LicenseManager(temp_dir, "0.1")
        # Create a fake license file
        license_file = lm.license_dir / "license_online.json"
        license_file.write_text('{"key": "test"}')
        
        assert license_file.exists()
        success, message = lm.deactivate()
        assert success
        assert not license_file.exists()
        assert not lm.state.valid

    def test_refresh_state(self, temp_dir):
        """Test refresh_state method."""
        lm = LicenseManager(temp_dir, "0.1")
        # Should not raise
        lm.refresh_state()
        assert not lm.state.valid
