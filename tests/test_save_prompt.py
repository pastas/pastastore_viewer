# -*- coding: utf-8 -*-
"""Tests for save prompt behavior on pastastore closing."""

from unittest.mock import MagicMock
import pandas as pd

try:
    from pastastore_viewer.pastastore_viewer import PastastoreViewer
except ImportError:
    from pastastore_viewer import PastastoreViewer


class DictConnector:
    pass


def test_store_has_content_empty():
    """Test _store_has_content with an empty store."""
    viewer = PastastoreViewer.__new__(PastastoreViewer)
    store = MagicMock()
    store.oseries.index = pd.Index([])
    store.stresses.index = pd.Index([])
    store.model_names = []
    viewer.store = store

    assert viewer._store_has_content() is False


def test_store_has_content_with_oseries():
    """Test _store_has_content with oseries."""
    viewer = PastastoreViewer.__new__(PastastoreViewer)
    store = MagicMock()
    store.oseries.index = pd.Index(["obs1"])
    store.stresses.index = pd.Index([])
    store.model_names = []
    viewer.store = store

    assert viewer._store_has_content() is True


def test_store_has_content_with_stresses():
    """Test _store_has_content with stresses."""
    viewer = PastastoreViewer.__new__(PastastoreViewer)
    store = MagicMock()
    store.oseries.index = pd.Index([])
    store.stresses.index = pd.Index(["prec1"])
    store.model_names = []
    viewer.store = store

    assert viewer._store_has_content() is True


def test_store_has_content_with_models():
    """Test _store_has_content with models."""
    viewer = PastastoreViewer.__new__(PastastoreViewer)
    store = MagicMock()
    store.oseries.index = pd.Index([])
    store.stresses.index = pd.Index([])
    store.model_names = ["ml1"]
    viewer.store = store

    assert viewer._store_has_content() is True


def test_should_prompt_save_empty_store():
    """Test that empty store does not prompt save even if marked modified or in-memory."""
    viewer = PastastoreViewer.__new__(PastastoreViewer)
    store = MagicMock()
    store.oseries.index = pd.Index([])
    store.stresses.index = pd.Index([])
    store.model_names = []
    store.conn = DictConnector()

    viewer.store = store
    viewer.store_modified = True
    viewer.dock_widget = MagicMock()
    viewer.dock_widget.store_path = None

    assert viewer._should_prompt_save() is False


def test_should_prompt_save_non_empty_in_memory_store():
    """Test that non-empty in-memory store prompts save."""
    viewer = PastastoreViewer.__new__(PastastoreViewer)
    store = MagicMock()
    store.oseries.index = pd.Index(["obs1"])
    store.stresses.index = pd.Index([])
    store.model_names = []
    store.conn = DictConnector()

    viewer.store = store
    viewer.store_modified = False
    viewer.dock_widget = MagicMock()
    viewer.dock_widget.store_path = None

    assert viewer._should_prompt_save() is True
