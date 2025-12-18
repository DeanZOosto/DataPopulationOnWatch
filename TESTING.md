# Testing Guide

This document describes the testing strategy and how to run tests for the OnWatch Data Population Automation project.

## Overview

The project includes comprehensive unit and integration tests that verify:
- Configuration management and validation
- Priority mapping for inquiry cases
- Run summary tracking and export file generation
- Integration workflows

All tests are designed to run **without requiring actual API connections**, making them safe to run in any environment.

## Running Tests

### Prerequisites

Install test dependencies:

```bash
pip3 install -r requirements.txt
```

This installs:
- `pytest` - Test framework
- `pytest-asyncio` - Async test support
- `pytest-mock` - Mocking utilities

### Run All Tests

```bash
python3 -m pytest tests/ -v
```

### Run Specific Test Files

```bash
# Configuration manager tests
python3 -m pytest tests/test_config_manager.py -v

# Priority mapping tests
python3 -m pytest tests/test_priority_mapping.py -v

# Run summary tests
python3 -m pytest tests/test_run_summary.py -v

# Integration tests
python3 -m pytest tests/test_integration.py -v
```

### Run Specific Test Cases

```bash
# Run a specific test function
python3 -m pytest tests/test_config_manager.py::TestConfigManager::test_load_config_basic -v
```

### Test Coverage

To generate coverage reports (requires `pytest-cov`):

```bash
pip3 install pytest-cov
python3 -m pytest tests/ --cov=. --cov-report=html
python3 -m pytest tests/ --cov=. --cov-report=term
```

Coverage report will be generated in `htmlcov/index.html`.

## Test Structure

### Unit Tests

**`tests/test_config_manager.py`**
- Configuration loading
- Environment variable substitution
- Configuration validation

**`tests/test_priority_mapping.py`**
- Priority string to number mapping (Low=201, Medium=101, High=1)
- Numeric range validation
- Default priority handling

**`tests/test_run_summary.py`**
- Run summary initialization
- Step tracking
- Created items tracking
- Export file generation

### Integration Tests

**`tests/test_integration.py`**
- End-to-end config validation workflow
- Export file generation workflow
- Priority mapping in inquiry workflow
- Rancher env vars tracking (even when step fails)

## Test Design Principles

1. **No External Dependencies**: Tests don't require actual API connections
2. **Isolated**: Each test is independent and can run in any order
3. **Fast**: Tests complete in seconds
4. **Comprehensive**: Cover critical functionality and edge cases
5. **Maintainable**: Clear test names and structure

## Writing New Tests

When adding new functionality, add corresponding tests:

1. **Unit Tests**: Test individual functions/methods in isolation
2. **Integration Tests**: Test workflows and interactions between components

Example test structure:

```python
def test_feature_name(self):
    """Test description of what this test verifies."""
    # Arrange: Set up test data
    test_data = {...}
    
    # Act: Execute the code being tested
    result = function_under_test(test_data)
    
    # Assert: Verify the result
    assert result == expected_value
```

## Continuous Integration

Tests can be integrated into CI/CD pipelines:

```yaml
# Example GitHub Actions workflow
- name: Run tests
  run: |
    pip3 install -r requirements.txt
    python3 -m pytest tests/ -v
```

## Troubleshooting

### Tests Fail with Import Errors

Ensure you're running tests from the project root directory:

```bash
cd /path/to/DataPopulationOnWatch
python3 -m pytest tests/ -v
```

### Tests Fail with Permission Errors

If you see permission errors, ensure test files are readable:

```bash
chmod +r tests/*.py
```

### Tests Require Network Access

If tests are trying to make network calls, check for missing mocks. All tests should work offline.

## Test Results

Expected output when all tests pass:

```
======================== 18 passed in 0.11s =========================
```

If tests fail, review the error messages and stack traces for details.
