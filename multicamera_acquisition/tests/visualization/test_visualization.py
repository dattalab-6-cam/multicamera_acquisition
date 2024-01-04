import multiprocessing as mp
import pdb
import time
from pathlib import Path

import cv2
import numpy as np
import os
import pytest
import matplotlib.pyplot as plt
import sys

from multicamera_acquisition.visualization import (
    MultiDisplay,
    load_first_frames,
    plot_image_grid
)

from multicamera_acquisition.acquisition import refactor_acquire_video, AcquisitionLoop

from multicamera_acquisition.video_utils import count_frames

from multicamera_acquisition.tests.writer.test_writers import (
    get_DummyFrames_process,
    fps,
    n_test_frames,
    dummy_frames_func
)

from multicamera_acquisition.tests.interfaces.test_ir_cameras import ( 
    camera_type,
    camera_brand
)

from multicamera_acquisition.interfaces.config import (
    partial_config_from_camera_list,
    create_full_camera_default_config,
)

from multicamera_acquisition.writer import (
    FFMPEG_Writer,
)

from multicamera_acquisition.tests.acquisition.test_acq_video import trigger_type



@pytest.fixture(scope="function")
def multidisplay_processes(tmp_path, fps, n_test_frames):
    """Generate linked MultiDisplay and DummyFrames processes for testing
    """
    config = MultiDisplay.default_display_config()
    queues = [mp.Queue() for c in config['camera_names']]
    dummy_frames_procs = [
        get_DummyFrames_process(fps, queue, n_test_frames)
        for queue in queues
    ]
    display = MultiDisplay(
        queues,
        config=config,
    )
    return (display, dummy_frames_procs)


def create_twocam_config(camera_brand, n_test_frames, trigger_type, fps):
    camera_list = [
        {"name": "top", "brand": camera_brand, "id": 0},
        {"name": "bottom", "brand": camera_brand, "id": 1}
    ]

    # Set the trigger behavior
    if trigger_type == "continuous":
        short_name = "continuous"
    elif trigger_type == "arduino":
        short_name = "arduino"
    for camera in camera_list:
        camera["short_name"] = short_name

    # Parse the "camera list" into a partial config
    partial_new_config = partial_config_from_camera_list(camera_list, fps)

    # Add ffmpeg writers to each camera
    # TODO: allow this to be nvc dynamically for testing. 
    writer_config = FFMPEG_Writer.default_writer_config(fps)
    # writer_config = NVC_Writer.default_writer_config(fps)
    for camera_name in partial_new_config["cameras"].keys():
        writer_config["camera_name"] = camera_name
        partial_new_config["cameras"][camera_name]["writer"] = writer_config

    # Create the full config, filling in defaults where necessary
    full_config = create_full_camera_default_config(partial_new_config)

    # Set up the acquisition loop part of the config
    acq_config = AcquisitionLoop.default_acq_loop_config()
    acq_config["max_frames_to_acqure"] = int(n_test_frames)
    full_config["acq_loop"] = acq_config

    display_config = MultiDisplay.default_display_config()
    full_config["rt_display"] = display_config

    return full_config


@pytest.mark.gui
def test_MultiDisplay(multidisplay_processes):

    # Get the writer and dummy frames proc
    display, dummy_frames_procs = multidisplay_processes
    
    # Start the writer and dummy frames proc
    display.start()
    for proc in dummy_frames_procs:
        proc.start()

    # Wait for the processes to finish
    for proc in dummy_frames_procs:
        proc.join(timeout=60)
    display.join(timeout=60)


@pytest.mark.gui
def test_acq_MultiDisplay(tmp_path, camera_brand, n_test_frames, trigger_type, fps):
    """Run an acquisition with display enabled.

    Note: when using emulated cameras, display will run faster than 'real time'
    because there is no delay to emulate framerate.
    """
    full_config = create_twocam_config(camera_brand, n_test_frames, trigger_type, fps)
    full_config['acq_loop']['display_frames'] = True

    # Run the func!
    save_loc, full_config = refactor_acquire_video(
        tmp_path,
        full_config,
        recording_duration_s=5,
        append_datetime=True,
        overwrite=False,
    )


def test_image_grid(tmp_path, camera_brand, trigger_type, fps):
    """Run an acquisition and display its first frames in a grid
    """

    full_config = create_twocam_config(camera_brand, 5, trigger_type, fps)
    save_loc, full_config = refactor_acquire_video(
        tmp_path,
        full_config,
        recording_duration_s=5,
        append_datetime=True,
        overwrite=False,
    )
    first_frames = load_first_frames(save_loc)
    fig, ax = plot_image_grid(first_frames, full_config['rt_display'])
    plt.show()