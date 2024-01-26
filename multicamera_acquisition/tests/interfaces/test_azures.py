import numpy as np
import pytest
import multiprocessing as mp

from multicamera_acquisition.interfaces.camera_base import get_camera


from multicamera_acquisition.interfaces.camera_azure import AzureCamera

from multicamera_acquisition.writer import get_writer


@pytest.fixture(scope="session")
def trigger_type(pytestconfig):
    return pytestconfig.getoption(
        "trigger_type"
    )  # default no_trigger (ie no trigger required), see conftest.py


@pytest.fixture(scope="function")
def camera(trigger_type):
    config = AzureCamera.default_camera_config()
    if trigger_type == "no_trigger":
        config["sync_mode"] = "true_master"
    else:
        config["sync_mode"] = "master"
    cam = AzureCamera(id=0, config=config)
    cam.init()
    yield cam
    cam.close()


class Test_Camera_InitAndStart:
    """Test the ability of the camera to initialize and start without a trigger."""

    def test_start(self, camera):
        camera.start()
        camera.stop()

    def test_grab_one(self, camera):
        camera.start()
        _, ir = camera.get_array(timeout=1000)
        print(ir)
        print(type(ir))
        assert isinstance(ir, np.ndarray)
        camera.stop()


def test_azure_acquire():
    """Test the ability of the Azure to acquire many images"""

    config = AzureCamera.default_camera_config()
    config["sync_mode"] = "true_master"
    cam = get_camera(brand="azure", id=0, config=config)
    cam.init()
    cam.start()
    for i in range(10):
        _, ir = cam.get_array(timeout=1000)
        assert isinstance(ir, np.ndarray)
    cam.stop()
    cam.close()


def test_azure_ir_writer(tmp_path):
    """Test the ir writer for the Azures"""
    config = AzureCamera.default_camera_config()
    config["sync_mode"] = "true_master"
    cam = get_camera(brand="azure", id=0, config=config)
    cam.init()

    write_queue = mp.Queue()
    video_file_name = tmp_path / "test.mp4"
    metadata_file_name = tmp_path / "test.csv"
    writer_config = {
        "fps": 30,
        "max_video_frames": 2592000,
        "quality": 15,
        "loglevel": "debug",
        "type": "ffmpeg",
        "pixel_format": "gray8",
        "output_px_format": "yuv420p",
        "video_codec": "libx264",
        "preset": "ultrafast",
        "gpu": None,
        "depth": False,
        "camera_name": "azure_bottom",
    }

    writer = get_writer(
        write_queue,
        video_file_name,
        metadata_file_name,
        writer_type=writer_config["type"],
        config=writer_config,
    )

    writer.start()
    cam.start()
    for i in range(10):
        depth, ir, timestamp = cam.get_array(timeout=1000, get_timestamp=True)
        write_queue.put(tuple([ir, timestamp, i]))

    cam.stop()
    write_queue.put(tuple())
    writer.join()
    cam.close()


def test_azure_depth_writer(tmp_path):
    """Test the depth writer for the Azures"""
    config = AzureCamera.default_camera_config()
    config["sync_mode"] = "true_master"
    cam = get_camera(brand="azure", id=0, config=config)
    cam.init()

    writer_depth_config = {
        "fps": 30,
        "max_video_frames": 2592000,
        "quality": 15,
        "loglevel": "debug",
        "type": "ffmpeg",
        "pixel_format": "gray16",
        "video_codec": "ffv1",
        "depth": True,
        "gpu": None,
        "camera_name": "azure_bottom",
    }

    write_queue_depth = mp.Queue()
    video_file_name_depth = tmp_path / "test_depth.avi"
    metadata_file_name_depth = tmp_path / "test_depth.csv"
    writer_depth = get_writer(
        write_queue_depth,
        video_file_name_depth,
        metadata_file_name_depth,
        writer_type=writer_depth_config["type"],
        config=writer_depth_config,
    )

    writer_depth.start()
    cam.start()
    for i in range(10):
        depth, ir, timestamp = cam.get_array(timeout=1000, get_timestamp=True)
        write_queue_depth.put(tuple([depth, timestamp, i]))

    cam.stop()
    write_queue_depth.put(tuple())
    writer_depth.join()
    cam.close()
