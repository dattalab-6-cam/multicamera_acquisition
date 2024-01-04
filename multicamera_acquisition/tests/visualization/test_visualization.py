import multiprocessing as mp
import pdb
import time
from pathlib import Path

import cv2
import numpy as np
import os
import pytest
import sys

from multicamera_acquisition.visualization import refactor_MultiDisplay

from multicamera_acquisition.video_io_ffmpeg import count_frames

from multicamera_acquisition.tests.writer.test_writers import (
    get_DummyFrames_process,
    fps,
    n_test_frames,
    dummy_frames_func
)


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



