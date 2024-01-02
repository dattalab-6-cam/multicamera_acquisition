import multiprocessing as mp
import pdb
import time
from pathlib import Path

import cv2
import numpy as np
import os
import pytest

from multicamera_acquisition.config.default_ffmpeg_writer_config import \
    default_ffmpeg_writer_config
from multicamera_acquisition.config.default_nvc_writer_config import \
    default_nvc_writer_config
from multicamera_acquisition.writer import FFMPEG_Writer  # NVC_Writer,

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


def dummy_frames_func(fps, queue):
    shape = (100, 100)  # 2D image
    frame = np.zeros((*shape, 3), dtype=np.uint8)
    for i in range(20):
        frame[:] = 0
        frame = cv2.putText(frame, str(i), (10, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        queue.put((frame[:, :, 0], i * 0.033, i))
        time.sleep(1 / fps)
    queue.put(())


def get_DummyFrames_process(fps, queue):
    process = mp.Process(target=dummy_frames_func, args=(fps, queue))
    return process


@pytest.fixture(scope="function")
def nvc_writer_processes(tmp_path, fps, DummyFrames):
    """Generate linked NVC_Writer and DummyFrames processes for testing
    """
    config = default_nvc_writer_config(fps)
    queue = mp.Queue()
    dummy_frames = DummyFrames(queue, fps)
    writer = NVC_Writer(
        queue, 
        video_file_name=str(tmp_path.join("test.mp4")), 
        metadata_file_name=str(tmp_path.join("test.csv")),
        config=config,
    )
    yield (writer, dummy_frames)

    # Stop the writer with an empty tuple
    queue.put(()) 

    # Join the dummy frames process
    dummy_frames.join()


@pytest.fixture(scope="function")
def ffmpeg_writer_processes(tmp_path, fps):
    """Generate linked FFMPEG_Writer and DummyFrames processes for testing
    """
    config = default_ffmpeg_writer_config(fps)
    config["camera_name"] = "test"
    queue = mp.Queue()
    dummy_frames_proc = get_DummyFrames_process(fps, queue)
    # tmp_path = Path('./multicamera_acquisition/scratch/tmp')
    writer = FFMPEG_Writer(
        queue, 
        # video_file_name=Path(str(tmp_path.join("test.mp4"))), 
        # metadata_file_name=Path(str(tmp_path.join("test.csv"))),
        video_file_name=tmp_path / "test.mp4",
        metadata_file_name=tmp_path / "test.csv",
        config=config,
    )
    return (writer, dummy_frames_proc)


def test_ffmpeg_writer(ffmpeg_writer_processes):

    # Get the writer and dummy frames proc
    writer, dummy_frames_proc = ffmpeg_writer_processes

    # Check that the writer is not running
    assert writer.frame_id == 0

    # Start the writer and dummy frames proc
    writer.start()
    dummy_frames_proc.start()

    # Wait for the processes to finish
    dummy_frames_proc.join(timeout=3)
    writer.join(timeout=3)

    # NB: this won't work! Because multiprocessing stuff runs in its own scope.
    # Would need to use a pipe / shared value to communicate between the two.
    # assert writer.frame_id == 20

    # Check that the video exists
    assert writer.video_file_name.exists()
    assert count_frames(str(writer.video_file_name)) == 20
