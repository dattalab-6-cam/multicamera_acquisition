import pytest

def pytest_addoption(parser):
    parser.addoption(
        "--rungui", action="store_true", default=False, help="run gui tests"
    )

def pytest_configure(config):
    config.addinivalue_line("markers", "gui: mark test as slow to run")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--rungui"):
        # --rungui given in cli: do not skip gui tests
        return
    skip_gui = pytest.mark.skip(reason="need --rungui option to run")
    for item in items:
        if "gui" in item.keywords:
            item.add_marker(skip_gui)