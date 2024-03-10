import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--runmcu", action="store_true", default=False, help="run micocontroller tests",
    )

    parser.addoption(
        "--runpyk4a", action="store_true", default=False, help="run pyk4a / azure tests",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "mcu: requires attached mcu to run")
    config.addinivalue_line("markers", "pyk4a: requires pyk4a lib to run")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runmcu"):
        # --rungui given in cli: do not skip gui tests
        pass
    else:
        _skip = pytest.mark.skip(reason="need --runmcu option to run")
        for item in items:
            if "mcu" in item.keywords:
                item.add_marker(_skip)

    if config.getoption("--runpyk4a"):
        # --rungui given in cli: do not skip gui tests
        pass
    else:
        _skip = pytest.mark.skip(reason="need --runpyk4a option to run")
        for item in items:
            if "pyk4a" in item.keywords:
                item.add_marker(_skip)
