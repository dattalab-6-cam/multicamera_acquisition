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
    refactor_MultiDisplay,
    load_first_frames,
    plot_image_grid
)

from multicamera_acquisition.acquisition import refactor_acquire_video

from multicamera_acquisition.video_io_ffmpeg import count_frames

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

from multicamera_acquisition.tests.acquisition.test_acq_video import create_twocam_config


@pytest.fixture(scope="function")
def multidisplay_processes(tmp_path, fps, n_test_frames):
    """Generate linked MultiDisplay and DummyFrames processes for testing
    """
    cameras = ['top', 'bottom']
    config = refactor_MultiDisplay.default_display_config(cameras)
    queues = [mp.Queue() for c in cameras]
    dummy_frames_procs = [
        get_DummyFrames_process(fps, queue, n_test_frames)
        for queue in queues
    ]
    display = refactor_MultiDisplay(
        queues,
        config=config,
    )
    return (display, dummy_frames_procs)


@pytest.mark.gui
def test_MultiDisplay(multidisplay_processes, n_test_frames):

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
def test_acq_MultiDisplay(tmp_path, camera_brand, n_test_frames):
    """Run an acquisition with display enabled.

    Note: when using emulated cameras, display will run faster than 'real time'
    because there is no delay to emulate framerate.
    """
    full_config = create_twocam_config(camera_brand, n_test_frames)
    full_config['acq_loop']['display_frames'] = True

    # Run the func!
    save_loc, full_config = refactor_acquire_video(
        tmp_path,
        full_config,
        recording_duration_s=5,
        append_datetime=True,
        overwrite=False,
    )


def test_image_grid(tmp_path, camera_brand):
    """Run an acquisition and display its first frames in a grid
    """

    full_config = create_twocam_config(camera_brand, 5)
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