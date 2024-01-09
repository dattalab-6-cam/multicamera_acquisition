# from ..writer.test_writers import nvc_writer_processes, n_test_frames

import multiprocessing as mp
import pytest

from multicamera_acquisition.tests.writer.test_writers import (
    fps,
    n_test_frames,
)
from multicamera_acquisition.tests.interfaces.test_ir_cameras import (
    camera_type, 
    camera,
)

from multicamera_acquisition.acquisition import (
    AcquisitionLoop
)

from multicamera_acquisition.interfaces.camera_basler import (
    BaslerCamera
)

from multicamera_acquisition.video_utils import count_frames

from multicamera_acquisition.tests.acquisition.test_acq_video import (
    writer_type,
)


def test_acq_loop_init(fps):
    loop = AcquisitionLoop(
        write_queue=mp.Queue(),
        display_queue=mp.Queue(),
        fps=fps,
        camera_device_index=None,
        camera_config=BaslerCamera.default_camera_config().copy(),
    )
    assert isinstance(loop.await_process, mp.synchronize.Event)
    assert isinstance(loop.await_main_thread, mp.synchronize.Event)
    assert loop.acq_config["frame_timeout"] == 1000


def test_acq_loop(tmp_path, fps, n_test_frames, camera_type, writer_type):
    """Test the whole darn thing!
    """

    if writer_type == "nvc":
        try:
            import PyNvCodec as nvc
        except ImportError:
            pytest.skip("PyNvCodec not installed, try running with --writer_type ffmpeg")

    print(camera_type)
    # Get the Camera config
    if camera_type == "basler_camera":
        from multicamera_acquisition.interfaces.camera_basler import BaslerCamera as Camera  
        id = 0  # or could dynamically pass serials
    elif camera_type == "basler_emulated":
        from multicamera_acquisition.interfaces.camera_basler import EmulatedBaslerCamera as Camera
        id = 0
    elif camera_type == "azure":
        from multicamera_acquisition.interfaces.camera_azure import AzureCamera as Camera
    else:
        raise NotImplementedError
    camera_config = Camera.default_camera_config().copy()
    camera_config["name"] = "test"
    camera_config["id"] = id
    camera_config["trigger"] = {"trigger_type": "no_trigger"}  # overwrite defaults to allow cam to run without triggers

    # Create the Writer process
    if writer_type == "nvc":
        from multicamera_acquisition.writer import NVC_Writer as Writer
    elif writer_type == "ffmpeg":
        from multicamera_acquisition.writer import FFMPEG_Writer as Writer
    write_queue = mp.Queue()
    writer_config = Writer.default_writer_config(fps).copy()
    writer_config["camera_name"] = "test"
    writer = Writer(
        write_queue,
        video_file_name=tmp_path / "test.mp4",
        metadata_file_name=tmp_path / "test.csv",
        config=writer_config,
    )

    # Create the AcquisitionLoop process
    acq_config = AcquisitionLoop.default_acq_loop_config().copy()
    acq_config["max_frames_to_acqure"] = int(n_test_frames)
    acq_loop = AcquisitionLoop(
        write_queue=write_queue,
        display_queue=None,
        fps=fps,
        camera_device_index=None,
        camera_config=camera_config,
        acq_loop_config=acq_config,
    )

    # Start the writer processes
    writer.start()

    # Start the acq loop
    acq_loop.start()
    acq_loop.await_process.wait()  # wait for the process to initialize
    acq_loop.await_main_thread.set()  # tell the process to start
    acq_loop.await_process.wait()  # wait for the process to start the camera

    # Wait for the processes to finish
    acq_loop.join(timeout=60)
    writer.join(timeout=60)

    # Check that the video exists
    assert writer.video_file_name.exists()
    if writer_type == "ffmpeg":
        assert count_frames(str(writer.video_file_name)) == n_test_frames
    elif writer_type == "nvc":
        assert count_frames(str(writer.video_file_name)) == n_test_frames
