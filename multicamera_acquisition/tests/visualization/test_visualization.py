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

import pdb

from multicamera_acquisition.visualization import (
    MultiDisplay,
    load_first_frames,
    plot_image_grid
)

from multicamera_acquisition.acquisition import refactor_acquire_video, AcquisitionLoop

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

from multicamera_acquisition.tests.acquisition.test_acq_video import (
    trigger_type,
)

from multicamera_acquisition.interfaces.config import (
    partial_config_from_camera_list,
    create_full_camera_default_config,
)

from multicamera_acquisition.writer import (
    FFMPEG_Writer,
)


@pytest.fixture(scope="function")
def multidisplay_processes(fps, n_test_frames):
    """Generate linked MultiDisplay and DummyFrames processes for testing
    """
    config = MultiDisplay.default_MultiDisplay_config().copy()
    queues = [mp.Queue() for _ in range(2)]
    dummy_frames_procs = [
        get_DummyFrames_process(fps, queue, n_test_frames)
        for queue in queues
    ]
    display = MultiDisplay(
        queues,
        ["left", "right"],
        [(0, 255), (0, 255)],
        config=config,
    )
    return (display, dummy_frames_procs)


def create_twocam_config(camera_brand, n_test_frames, fps, trigger_type):
    camera_list = [
        {"name": "top", "brand": camera_brand, "id": 0, "trigger_type": trigger_type},
        {"name": "bottom", "brand": camera_brand, "id": 1, "trigger_type": trigger_type}
    ]

    # Parse the "camera list" into a partial config
    partial_new_config = partial_config_from_camera_list(camera_list)

    # Add ffmpeg writers to each camera
    # TODO: allow this to be nvc dynamically for testing. 
    for camera_name in partial_new_config["cameras"].keys():
        ffmpeg_writer_config = FFMPEG_Writer.default_writer_config(fps).copy()
        ffmpeg_writer_config["camera_name"] = camera_name
        partial_new_config["cameras"][camera_name]["writer"] = ffmpeg_writer_config

    # Create the full config, filling in defaults where necessary
    full_config = create_full_camera_default_config(partial_new_config, fps)
    full_config["globals"] = dict(fps=fps, arduino_required=False)

    # Set up the acquisition loop part of the config
    acq_config = AcquisitionLoop.default_acq_loop_config().copy()
    acq_config["max_frames_to_acqure"] = n_test_frames
    full_config["acq_loop"] = acq_config

    display_config = MultiDisplay.default_MultiDisplay_config().copy()
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
def test_acq_MultiDisplay(tmp_path, camera_brand, n_test_frames, fps, trigger_type):
    """Run an acquisition with display enabled.

    Note: when using emulated cameras, display will run faster than 'real time'
    because there is no delay to emulate framerate.
    """
    full_config = create_twocam_config(camera_brand, n_test_frames, fps, trigger_type)

    # Set cameras to be displayed
    for camera in full_config["cameras"].values():
        camera["display"]["display_frames"] = True

    # Run the func!
    save_loc, vid_file_name, full_config = refactor_acquire_video(
        tmp_path,
        full_config,
        recording_duration_s=(n_test_frames / fps),
        append_datetime=True,
        overwrite=False,
    )


@pytest.mark.gui
def test_displayRange(tmp_path, camera_brand, n_test_frames, fps):
    """Test the display range functionality of MultiDisplay
    """
    full_config = create_twocam_config(camera_brand, n_test_frames, fps, trigger_type="no_trigger")

    # Set display config as desired for the test
    for camera in full_config["cameras"].values():
        camera["display"]["display_frames"] = True
    camera_names = list(full_config["cameras"].keys())
    full_config["cameras"][camera_names[0]]["display"]["display_range"] = (0, 100)
    full_config["cameras"][camera_names[1]]["display"]["display_range"] = (220, 255)

    # Run the func!
    save_loc, vid_file_name, full_config = refactor_acquire_video(
        tmp_path,
        full_config,
        recording_duration_s=(n_test_frames / fps),
        append_datetime=True,
        overwrite=False,
    )


def test_image_grid(tmp_path, camera_brand, fps):
    """Run an acquisition and display its first frames in a grid
    """

    n_test_frames = 5
    full_config = create_twocam_config(camera_brand, n_test_frames, fps, trigger_type="no_trigger")
    
    save_loc, vid_file_name, full_config = refactor_acquire_video(
        tmp_path,
        full_config,
        recording_duration_s=(n_test_frames / fps),
        append_datetime=True,
        overwrite=False,
    )
    print(full_config)
    first_frames = load_first_frames(save_loc)
    fig, ax = plot_image_grid(
        images=first_frames, 
        display_config=full_config['rt_display'], 
        camera_names=list(full_config['cameras'].keys()),
        display_ranges=[cam["display"]["display_range"] for cam in full_config["cameras"].values() if cam["display"]["display_frames"]]
    )
    plt.show()
