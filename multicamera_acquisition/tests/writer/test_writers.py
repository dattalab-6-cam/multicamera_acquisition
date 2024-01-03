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


@pytest.fixture(scope="session")
def fps(pytestconfig):
    """A session-wide fixture to return the desired fps.

    See test_cameras.py::camera for possible camera options.

    Example usage:
        >>> pytest ./path/to/test_camera_basler.py --camera_type basler_emulated
        >>> pytest ./path/to/test_camera_basler.py --camera_type basler_camera
    """
    return pytestconfig.getoption("fps", default=30)


@pytest.fixture(scope="session")
def n_test_frames(pytestconfig):
    """A session-wide fixture to return the desired number of test frames per movie.
    """
    return pytestconfig.getoption("n_test_frames", default=200)


def dummy_frames_func(fps, queue, n_test_frames):
    """A dummy frames function to test the writers.
    Must be separately defined from the get_DummyFrames_process function
    to avoid pickling issues.
    """
    shape = (640, 640)  # 2D image  (must be at least 145 x ? for NVC writer)
    frame = np.zeros((*shape, 3), dtype=np.uint8)
    for i in range(n_test_frames):
        frame[:] = 0
        frame = cv2.putText(frame, str(i), (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        queue.put((frame[:, :, 0], i * 0.033, i))
        time.sleep(1 / fps)
    queue.put(())


def get_DummyFrames_process(fps, queue, n_test_frames):
    """Get a DummyFrames process for testing.
    """
    process = mp.Process(target=dummy_frames_func, args=(fps, queue, n_test_frames))
    return process


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


@pytest.fixture(scope="function")
def ffmpeg_writer_processes(tmp_path, fps, n_test_frames):
    """Generate linked FFMPEG_Writer and DummyFrames processes for testing
    """
    config = FFMPEG_Writer.default_writer_config(fps)
    config["camera_name"] = "test"  
    config["loglevel"] = "debug"
    queue = mp.Queue()
    dummy_frames_proc = get_DummyFrames_process(fps, queue, n_test_frames)
    writer = FFMPEG_Writer(
        queue, 
        video_file_name=tmp_path / "test.mp4",
        metadata_file_name=tmp_path / "test.csv",
        config=config,
    )
    return (writer, dummy_frames_proc)


def test_ffmpeg_writer(ffmpeg_writer_processes, n_test_frames):

    # Get the writer and dummy frames proc
    writer, dummy_frames_proc = ffmpeg_writer_processes

    # Check that the writer is not running
    assert writer.frame_id == 0

    # Start the writer and dummy frames proc
    writer.start()
    dummy_frames_proc.start()

    # Wait for the processes to finish
    # NB: 5 seconds seems like a lot, but it fails at lower timeouts.
    dummy_frames_proc.join(timeout=5)
    writer.join(timeout=5)

    # NB: this won't work! Because multiprocessing stuff runs in its own scope.
    # Would need to use a pipe / shared value to communicate between the two.
    # assert writer.frame_id == 20

    # Check that the video exists
    assert writer.video_file_name.exists()
    assert count_frames(str(writer.video_file_name)) == n_test_frames
