import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--camera_type", 
        action="store", 
        default="basler_emulated"
    )
    parser.addoption(
        "--n_test_frames",
        action="store",
        default=200,
    )

    parser.addoption(
        "--trigger_type",
        action="store",
        default="continuous",
    )