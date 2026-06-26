# -*- coding: utf-8 -*-
import sys
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

# Define Mock base classes
class MockBase:
    def __init__(self, *args, **kwargs):
        pass

widgets_mock = MagicMock()
widgets_mock.QDialog = MockBase
widgets_mock.QWidget = MockBase
widgets_mock.QGroupBox = MockBase
widgets_mock.QTabWidget = MockBase
widgets_mock.QSplitter = MockBase

core_mock = MagicMock()
gui_mock = MagicMock()

# Patch sys.modules only during import to avoid polluting the test session
with patch.dict(sys.modules, {
    "qgis": MagicMock(),
    "qgis.PyQt": MagicMock(),
    "qgis.PyQt.QtWidgets": widgets_mock,
    "qgis.PyQt.QtCore": MagicMock(),
    "qgis.PyQt.QtGui": MagicMock(),
    "qgis.core": core_mock,
    "qgis.gui": gui_mock,
}):
    from pastastore_viewer.bro_import_dialog import BROImportDialog


class MockItem:
    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text


class MockListWidget:
    def __init__(self, selected_texts):
        self._selected = [MockItem(t) for t in selected_texts]

    def selectedItems(self):
        return self._selected


def test_filter_dataframe():
    # Construct a sample DataFrame
    df = pd.DataFrame({
        "status": ["volledigBeoordeeld", "voorlopig", "onbekend"],
        "qualifier": ["goedgekeurd", "afgekeurd", "nogNietBeoordeeld"],
        "observation_type": ["reguliereMeting", "controleMeting", "reguliereMeting"],
        "value": [10.0, 12.5, 9.8]
    })

    # Create a mock dialog instance
    mock_self = MagicMock(spec=BROImportDialog)
    
    # Mock list widgets with selected values
    mock_self.list_status = MockListWidget(["volledigBeoordeeld", "voorlopig"])
    mock_self.list_qualifier = MockListWidget(["goedgekeurd", "nogNietBeoordeeld"])
    mock_self.list_obs_type = MockListWidget(["reguliereMeting"])

    # Run filtering using the class method bound to the mock self
    filtered = BROImportDialog._filter_dataframe(mock_self, df)

    # Validate output
    # Row 0: volledigBeoordeeld, goedgekeurd, reguliereMeting -> matches all -> Keep
    # Row 1: voorlopig, afgekeurd, controleMeting -> qualifier/obs_type don't match -> Filter out
    # Row 2: onbekend, nogNietBeoordeeld, reguliereMeting -> status doesn't match -> Filter out
    assert len(filtered) == 1
    assert filtered.iloc[0]["value"] == 10.0

    # Test when DataFrame is None
    assert BROImportDialog._filter_dataframe(mock_self, None) is None

    # Test when DataFrame does not have columns
    series = pd.Series([1, 2, 3])
    filtered_series = BROImportDialog._filter_dataframe(mock_self, series)
    assert filtered_series is series
