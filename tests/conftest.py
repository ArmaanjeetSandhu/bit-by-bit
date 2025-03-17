import pytest


def pytest_addoption(parser):
    """Add command-line options for BitTorrent tests."""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests that require network",
    )
    parser.addoption(
        "--slow",
        action="store_true",
        default=False,
        help="Run slow tests that take a long time to complete",
    )
    parser.addoption(
        "--torrent-file", default=None, help="Path to a real torrent file for testing"
    )
    parser.addoption("--magnet-link", default=None, help="A magnet link for testing")


def pytest_configure(config):
    """Configure pytest based on command-line options."""
    config.addinivalue_line(
        "markers", "integration: mark test as requiring network access"
    )
    config.addinivalue_line("markers", "slow: mark test as slow to run")


def pytest_collection_modifyitems(config, items):
    """Skip tests based on command-line options."""
    skip_integration = pytest.mark.skip(reason="needs --integration option to run")
    skip_slow = pytest.mark.skip(reason="needs --slow option to run")
    for item in items:
        if "integration" in item.keywords and not config.getoption("--integration"):
            item.add_marker(skip_integration)
        if "slow" in item.keywords and not config.getoption("--slow"):
            item.add_marker(skip_slow)


@pytest.fixture
def real_torrent_file(request):
    """Return the path to a real torrent file for testing, if provided."""
    torrent_file = request.config.getoption("--torrent-file")
    if not torrent_file:
        pytest.skip("needs --torrent-file option to run")
    return torrent_file


@pytest.fixture
def real_magnet_link(request):
    """Return a real magnet link for testing, if provided."""
    magnet_link = request.config.getoption("--magnet-link")
    if not magnet_link:
        pytest.skip("needs --magnet-link option to run")
    return magnet_link
