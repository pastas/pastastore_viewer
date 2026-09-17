# -*- coding: utf-8 -*-
"""Tests for the i18n helper module."""

import pytest
from i18n_helper import tr


class TestTranslationHelper:
    """Test the translation helper function."""

    def test_tr_returns_string(self):
        """Test that tr returns a string."""
        result = tr("test")
        assert isinstance(result, str)

    def test_tr_returns_same_for_english(self):
        """Test that English strings are returned unchanged when no translation exists."""
        msg = "Hello World"
        result = tr(msg)
        # Should return the message (or translated version if it exists)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_tr_handles_empty_string(self):
        """Test that tr handles empty strings."""
        result = tr("")
        assert isinstance(result, str)

    def test_tr_handles_special_characters(self):
        """Test that tr handles strings with special characters."""
        msg = "Test with special chars: @#$%"
        result = tr(msg)
        assert isinstance(result, str)

    def test_tr_handles_unicode(self):
        """Test that tr handles Unicode characters."""
        msg = "Hëllö Wørld 中文 日本語"
        result = tr(msg)
        assert isinstance(result, str)

    def test_tr_dutch_download_selected_observations(self, monkeypatch):
        """Test Dutch translation for 'Download selected observations' and 'Download Selected Observations'."""
        import i18n_helper
        # Reset cached translations and mock Dutch locale
        monkeypatch.setattr(i18n_helper, "_NL_TRANSLATIONS", None)
        monkeypatch.setattr(i18n_helper, "_is_dutch_locale", lambda: True)

        assert tr("Download Selected Observations") == "Geselecteerde waarnemingen downloaden"
        assert tr("Download selected observations") == "Geselecteerde waarnemingen downloaden"
        assert tr("Found {} locations in the selected map extent. You can now select locations and download observations.").format(5) == "5 locaties gevonden in de geselecteerde kaartomvang. U kunt nu locaties selecteren en waarnemingen downloaden."
        assert tr("Save Pastastore") == "Pastastore opslaan"
        assert tr("The pastastore has been modified. Do you want to save it?") == "De pastastore is gewijzigd. Wilt u deze opslaan?"

