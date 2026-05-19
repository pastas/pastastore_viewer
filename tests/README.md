# Automated Tests for Pastastore Viewer

This directory contains comprehensive automated tests for the Pastastore Viewer QGIS plugin.

## Test Structure

```
tests/
├── __init__.py                  # Package initialization
├── conftest.py                  # Pytest configuration and shared fixtures
├── test_license_manager.py      # License management tests
├── test_i18n_helper.py         # Translation helper tests
├── test_plugin_structure.py    # Plugin structure validation
├── test_data_utilities.py      # Data processing utilities tests
└── test_ui_basics.py           # Basic UI component tests
```

## Test Categories

### Unit Tests (Marked as `@pytest.mark.unit`)
Fast tests that don't require external dependencies:
- License manager functionality
- URL normalization
- Machine ID generation
- i18n helpers
- Plugin structure validation
- Data utilities (pandas, numpy operations)

### Integration Tests (Marked as `@pytest.mark.integration`)
Tests that may require QGIS environment:
- UI component imports
- Dialog initialization (when QGIS available)

### Slow Tests (Marked as `@pytest.mark.slow`)
Long-running tests that are skipped by default

## Installation

### Install Test Dependencies

```bash
pip install -r tests-requirements.txt
```

This installs:
- **pytest**: Test runner framework
- **pytest-cov**: Code coverage reporting
- **pytest-mock**: Mocking utilities
- **pytest-xdist**: Parallel test execution

## Running Tests

### Run All Unit Tests
```bash
pytest tests/ -m unit -v
```

### Run All Tests
```bash
pytest tests/ -v
```

### Run Specific Test File
```bash
pytest tests/test_license_manager.py -v
```

### Run Specific Test
```bash
pytest tests/test_license_manager.py::TestLicenseState::test_default_state -v
```

### Run Tests in Parallel
```bash
pytest tests/ -n auto
```

### Generate Coverage Report
```bash
pytest tests/ --cov=. --cov-report=html --cov-report=term
```

This creates an HTML coverage report in `htmlcov/index.html`

### Run Only Fast Tests (Skip Slow)
```bash
pytest tests/ -m "not slow" -v
```

### Run Tests with Detailed Output
```bash
pytest tests/ -vv --tb=long
```

## Test Examples

### License Manager Tests
```python
def test_machine_id_is_consistent(self):
    """Test that machine_id is consistent across calls."""
    mid1 = _machine_id()
    mid2 = _machine_id()
    assert mid1 == mid2
```

### Plugin Structure Tests
```python
def test_metadata_has_required_fields(self, plugin_dir):
    """Test that metadata.txt has required QGIS fields."""
    metadata_path = Path(plugin_dir) / "metadata.txt"
    content = metadata_path.read_text()
    assert "name=" in content
    assert "version=" in content
```

### Data Utilities Tests
```python
def test_series_nan_masking(self):
    """Test masking NaN values in a Series."""
    series = pd.Series([1.0, np.nan, 3.0, np.nan, 5.0])
    mask = ~np.isnan(series.values)
    filtered = series[mask]
    assert len(filtered) == 3
```

## Continuous Integration

Tests are automatically run on GitHub using GitHub Actions:

- **Trigger**: Pushes to `main` or `develop` branches, and on pull requests
- **Python Versions**: 3.8, 3.9, 3.10, 3.11
- **Jobs**:
  - Unit tests with coverage reporting
  - Code style checks (black, isort, flake8)
  - Coverage upload to Codecov

See `.github/workflows/tests.yml` for workflow definition.

## Adding New Tests

1. Create test file in `tests/` directory with `test_*.py` naming
2. Use descriptive class and method names
3. Add pytest markers (`@pytest.mark.unit`, etc.)
4. Include docstrings explaining what is tested

### Example Test
```python
# -*- coding: utf-8 -*-
"""Tests for new module."""

import pytest
from new_module import MyClass


@pytest.mark.unit
class TestMyClass:
    """Test MyClass functionality."""
    
    def test_initialization(self):
        """Test MyClass initialization."""
        obj = MyClass()
        assert obj is not None
    
    def test_method_returns_value(self):
        """Test that method returns expected value."""
        obj = MyClass()
        result = obj.my_method()
        assert result == expected_value
```

## Fixtures

Common test fixtures defined in `conftest.py`:

- **temp_dir**: Temporary directory for test files
- **plugin_dir**: Plugin directory path
- **license_dir**: Temporary license directory

### Using Fixtures
```python
def test_something(self, temp_dir, plugin_dir):
    """Test with fixtures."""
    # temp_dir: path to temporary directory
    # plugin_dir: path to plugin directory
    pass
```

## Test Coverage Goals

- License Manager: > 90% coverage
- Plugin structure validation: 100% coverage
- Data utilities: > 85% coverage
- UI components: > 50% coverage (limited by QGIS dependency)

## Troubleshooting

### Tests Skip QGIS-dependent Tests
If tests marked with `@pytest.mark.qgis` are skipped, it means QGIS environment is not available. This is expected in non-QGIS environments.

### Import Errors
Ensure dependencies are installed: `pip install -r requirements.txt -r tests-requirements.txt`

### Path Issues
Tests use relative imports. Run pytest from the repository root:
```bash
cd /path/to/pastastore_viewer
pytest tests/
```

## References

- [Pytest Documentation](https://docs.pytest.org/)
- [Pytest Fixtures](https://docs.pytest.org/en/latest/fixture.html)
- [Pytest Markers](https://docs.pytest.org/en/latest/example/markers.html)
- [Coverage.py](https://coverage.readthedocs.io/)
