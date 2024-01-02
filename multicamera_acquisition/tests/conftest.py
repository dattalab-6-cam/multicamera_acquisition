import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--camera_type", 
        action="store", 
        default="basler_emulated"
    )