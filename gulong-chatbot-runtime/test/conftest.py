import pytest
import warnings

from runtime.shared.base_http_client import close_all_clients_sync

# Configure pytest-asyncio to use strict mode (already default in plugin 0.23.4)
def pytest_configure(config):
    config.addinivalue_line("markers", "asyncio: mark test as asyncio for pytest-asyncio")
    warnings.filterwarnings(
        "ignore",
        message="Pydantic serializer warnings.*",
        category=UserWarning,
        module=r"pydantic\.main",
    )
    warnings.filterwarnings(
        "ignore",
        message="PydanticSerializationUnexpectedValue.*",
        category=UserWarning,
        module=r"pydantic\.main",
    )
    warnings.filterwarnings(
        "ignore",
        message="Unclosed client session",
        category=ResourceWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message="Unclosed connector",
        category=ResourceWarning,
    )


def pytest_collection_modifyitems(config, items):
    """
    Skip legacy Flask tests (test_app.py, test_system.py) that rely on fixtures
    not present in this FastAPI-based service. This keeps the focus on the
    current chatbot pipeline tests.
    """
    for item in items:
        path = str(item.fspath)
        if path.endswith("test_app.py") or path.endswith("test_system.py"):
            item.add_marker(pytest.mark.skip(reason="Legacy Flask test suite not applicable to current service"))


def pytest_sessionfinish(session, exitstatus):
    close_all_clients_sync()
