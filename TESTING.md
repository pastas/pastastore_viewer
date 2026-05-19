# Quick Test Reference

## Quick Start

```bash
# Install test dependencies
pip install -r tests-requirements.txt

# Run all unit tests
pytest tests/ -m unit -v

# Run with coverage
pytest tests/ --cov=. --cov-report=term

# Run specific test
pytest tests/test_license_manager.py::TestLicenseManager::test_initialization -v

# Run in parallel
pytest tests/ -n auto
```

## Common Commands

| Command | Purpose |
|---------|---------|
| `pytest tests/ -m unit -v` | Run all unit tests verbosely |
| `pytest tests/ --cov=. --cov-report=html` | Generate HTML coverage report |
| `pytest tests/ -n auto` | Run tests in parallel |
| `pytest tests/ -k test_license` | Run tests matching "test_license" |
| `pytest tests/ --tb=short` | Show short tracebacks |
| `pytest tests/ -x` | Stop on first failure |
| `pytest tests/test_license_manager.py` | Run specific test file |

## Test Structure

```
tests/
├── __init__.py
├── conftest.py                    # Shared fixtures
├── test_license_manager.py        # License manager tests (45+ tests)
├── test_i18n_helper.py           # i18n tests (5+ tests)
├── test_plugin_structure.py      # Structure tests (11+ tests)
├── test_data_utilities.py        # Data utilities tests (10+ tests)
├── test_ui_basics.py             # UI tests (3+ tests)
└── README.md                      # Detailed documentation
```

## Test Markers

- `@pytest.mark.unit` - Fast tests, no QGIS needed
- `@pytest.mark.integration` - May need QGIS
- `@pytest.mark.slow` - Long-running tests
- `@pytest.mark.qgis` - Requires QGIS environment

## Fixtures Available

```python
@pytest.fixture
def temp_dir():
    """Temporary directory for test files"""

@pytest.fixture
def plugin_dir():
    """Plugin directory path"""

@pytest.fixture
def license_dir(temp_dir):
    """Temporary license directory"""
```

## Running Tests

### From Command Line
```bash
cd /path/to/pastastore_viewer
pytest tests/
```

### Using Test Runner Script
```bash
python run_tests.py               # Run unit tests
python run_tests.py --all         # Run all tests
python run_tests.py --coverage    # With coverage
python run_tests.py --parallel    # In parallel
python run_tests.py --file test_name  # Specific file
```

## GitHub Actions

Tests run automatically on:
- Push to `main` or `develop`
- Pull requests

Configuration: `.github/workflows/tests.yml`

## Coverage Reports

After running with `--cov`:
- Terminal report shows percentages
- HTML report: `htmlcov/index.html`
- XML report: `coverage.xml` (for CI/CD)

## Adding Tests

1. Create test in `tests/test_*.py`
2. Use `TestClass` naming
3. Use `test_*` method naming
4. Add docstrings
5. Add pytest markers
6. Use fixtures

```python
@pytest.mark.unit
class TestMyFeature:
    def test_something(self, temp_dir):
        """Test that something works."""
        # Test code
        assert result == expected
```

## Troubleshooting

- **ImportError**: Ensure `pip install -r requirements.txt` first
- **QGIS tests skip**: Normal when QGIS not installed
- **Path errors**: Run from repo root: `cd pastastore_viewer && pytest`
- **Coverage errors**: Install: `pip install pytest-cov`
