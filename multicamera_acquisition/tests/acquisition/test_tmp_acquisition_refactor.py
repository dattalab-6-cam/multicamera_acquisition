import csv
import logging
import multiprocessing as mp
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
import serial
import yaml
from tqdm import tqdm

from multicamera_acquisition.acquisition import (
    refactor_acquire_video
)
from multicamera_acquisition.interfaces.config import (
    create_full_camera_default_config,
)
from multicamera_acquisition.interfaces.config import partial_config_from_camera_list

PACKAGE_DIR = Path(__file__).resolve().parents[2]  # multicamera_acquisition/


@pytest.fixture(scope="session")
def camera_type(pytestconfig):
    """A session-wide fixture to return the camera type
    from the command line option.

    See test_cameras.py::camera for possible camera options.

    Example usage:
        >>> pytest ./path/to/test_camera_basler.py --camera_type basler_emulated
        >>> pytest ./path/to/test_camera_basler.py --camera_type basler_camera
    """
    return pytestconfig.getoption("camera_type")


@pytest.fixture(scope="function")
def camera_brand(camera_type):
    if camera_type == 'basler_camera':
        brand = "basler"
    elif camera_type == 'basler_emulated':
        brand = "basler_emulated"
    else:
        raise ValueError("Invalid camera type")
    return brand


def test_refactor_acquire_video(camera_brand):
    """
    """
    # Params
    save_location = f"{PACKAGE_DIR}/scratch/test_recording"
    if camera_brand == "basler":
        camera_list = [
            {"name": "top", "brand": camera_brand, "id": "40347941"},
            {"name": "bottom", "brand": camera_brand, "id": "40393557"}
        ]
    elif camera_brand == "basler_emulated":
        camera_list = [
            {"name": "top", "brand": camera_brand, "id": 0},
            {"name": "bottom", "brand": camera_brand, "id": 1}
        ]
    fps = 30
    rt_display_params = None 

    # set up the configs
    partial_new_config = partial_config_from_camera_list(camera_list, fps)
    full_config = create_full_camera_default_config(partial_new_config)

    refactor_acquire_video(
        save_location,
        full_config,
        recording_duration_s=5,
        rt_display_params=rt_display_params,
        append_datetime=True,
        overwrite=False,
    )
