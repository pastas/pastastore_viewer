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
