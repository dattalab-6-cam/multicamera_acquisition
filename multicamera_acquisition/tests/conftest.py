import pytest


def pytest_addoption(parser):
    parser.addoption("--camera_type", action="store", default="basler_emulated")

    parser.addoption(
        "--trigger_type",
        action="store",
        default="no_trigger",
    )

    parser.addoption(
        "--n_test_frames",
        action="store",
        default=200,
    )

    parser.addoption(
        "--writer_type",
        action="store",
        default="nvc",
    )

    parser.addoption(
        "--fps",
        action="store",
        default=30,
    )

    parser.addoption(
        "--runall", action="store_true", default=False, help="run all tests (defaults, plus gui, mcu, and pyk4a)",
    )
