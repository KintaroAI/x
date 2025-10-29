# Tests

This directory contains tests for the scheduler system.

## Running Tests

### Prerequisites
Make sure the development environment is running:
```bash
make dev
```

### Available Test Commands

- `make test` - Run all tests
- `make test-unit` - Run unit tests only
- `make test-integration` - Run integration tests only  
- `make test-scheduler` - Run scheduler tests only
- `make test-coverage` - Run tests with coverage report

### Test Structure

- `conftest.py` - Test configuration and fixtures
- `test_scheduler_service.py` - Unit tests for schedule resolution
- `test_scheduler_tasks.py` - Unit tests for scheduler tasks
- `test_scheduler_integration.py` - Integration tests with database
- `test_scheduler.py` - Manual test script (legacy)

### Test Categories

Tests are marked with pytest markers:
- `@pytest.mark.unit` - Unit tests (mocked dependencies)
- `@pytest.mark.integration` - Integration tests (real database)

### Coverage

Coverage reports are generated in HTML format in `htmlcov/` directory when running `make test-coverage`.

## Manual Testing

For manual testing of scheduler functionality, you can also use:

```bash
# Open shell in API container
make shell-api

# Then run the manual test script
python tests/test_scheduler.py
```
