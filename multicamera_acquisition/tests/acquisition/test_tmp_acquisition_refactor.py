import csv
import logging
import multiprocessing as mp
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import serial
import yaml
from tqdm import tqdm

from multicamera_acquisition.acquisition import (
    refactor_acquire_video
)

PACKAGE_DIR = Path(__file__).resolve().parents[2]  # multicamera_acquisition/


def test_refactor_acquire_video():
    """
    """
    # Params
    save_location = f"{PACKAGE_DIR}/scratch/test_recording"
    camera_list = [
        {"name": "top", "brand": "basler_emulated", "id": 0},
        {"name": "bottom", "brand": "basler_emulated", "id": 1}
    ]
    fps = 30
    recording_duration_s = 60 
    config_file = None
    display_params = None 
    append_datetime = True
    overwrite = False

    refactor_acquire_video(
        save_location,
        camera_list,
        fps,
        recording_duration_s,
        config_file,
        display_params,
        append_datetime,
        overwrite
    )
