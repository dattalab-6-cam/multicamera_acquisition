import multiprocessing as mp
import pdb
import time
from pathlib import Path

import cv2
import numpy as np
import os
import pytest


from multicamera_acquisition.writer import FFMPEG_Writer

from multicamera_acquisition.video_io_ffmpeg import count_frames

from multicamera_acquisition.writer import (
    get_DummyFrames_process,
    fps,
    n_test_frames,
    dummy_frames_func
)




@pytest.fixture(scope="function")
def nvc_writer_processes(tmp_path, fps, n_test_frames):
    """Generate linked NVC_Writer and DummyFrames processes for testing
    """
    from multicamera_acquisition.writer import NVC_Writer
    config = NVC_Writer.default_writer_config(fps)
    config["camera_name"] = "test"
    queue = mp.Queue()
    dummy_frames_proc = get_DummyFrames_process(fps, queue, n_test_frames)
    writer = NVC_Writer(
        queue, 
        video_file_name=tmp_path / "test.mp4",
        metadata_file_name=tmp_path / "test.csv",
        config=config,
    )
    return (writer, dummy_frames_proc)


def test_NVC_writer(nvc_writer_processes, n_test_frames):

    # Get the writer and dummy frames proc
    writer, dummy_frames_proc = nvc_writer_processes

    # Check that the writer is not running
    assert writer.frame_id == 0

    # Start the writer and dummy frames proc
    writer.start()
    dummy_frames_proc.start()

    # Wait for the processes to finish
    dummy_frames_proc.join(timeout=60)
    writer.join(timeout=60)

    # NB: this won't work! Because multiprocessing stuff runs in its own scope.
    # Would need to use a pipe / shared value to communicate between the two.
    # assert writer.frame_id == 20

    # Check that the video exists
    assert writer.video_file_name.exists()
    assert count_frames(str(writer.video_file_name).replace(".mp4", ".muxed.mp4")) == n_test_frames

