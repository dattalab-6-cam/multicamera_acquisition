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

    # validate passed camera type
    # should be either basler_camera or basler_emulated
    if config.getoption("--camera_type") not in ["basler_camera", "basler_emulated"]:
        raise ValueError(
            "Invalid camera type.  Must be one of: ['basler_camera', 'basler_emulated']"
        )

def pytest_collection_modifyitems(config, items):

    # If --runall is given in cli: do not skip any tests
    if config.getoption("--runall"):
        return

    # Otherwise, skip tests depending on options
    if config.getoption("--runmcu"):
        pass
    else:
        _skip = pytest.mark.skip(reason="need --runmcu option to run")
        for item in items:
            if "mcu" in item.keywords:
                item.add_marker(_skip)

    if config.getoption("--runpyk4a"):
        pass
    else:
        _skip = pytest.mark.skip(reason="need --runpyk4a option to run")
        for item in items:
            if "pyk4a" in item.keywords:
                item.add_marker(_skip)
