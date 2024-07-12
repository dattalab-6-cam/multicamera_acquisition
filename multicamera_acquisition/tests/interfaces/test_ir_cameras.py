import numpy as np
import pytest

from multicamera_acquisition.interfaces.camera_basler import (
    BaslerCamera,
    CameraError,
    EmulatedBaslerCamera,
)


@pytest.fixture(scope="session")
def camera_type(pytestconfig):
    """A session-wide fixture to return the camera type
    from the command line option.

    See test_cameras.py::camera for possible camera options.

    Example usage:
        >>> pytest ./path/to/test_camera_basler.py --camera_type basler_emulated
        >>> pytest ./path/to/test_camera_basler.py --camera_type basler_camera
    """
    return pytestconfig.getoption("camera_type")  # default emulated, see conftest.py


@pytest.fixture(scope="function")
def camera_brand(camera_type):
    if camera_type == "basler_camera":
        brand = "basler"
    elif camera_type == "basler_emulated":
        brand = "basler_emulated"
    elif camera_type == "uvc":
        brand = "uvc"
    else:
        raise ValueError("Invalid camera type")
    return brand


@pytest.fixture(scope="session")
def fps(pytestconfig):
    """A session-wide fixture to return the desired fps.

    See test_cameras.py::camera for possible camera options.

    Example usage:
        >>> pytest ./path/to/test_camera_basler.py --camera_type basler_emulated
        >>> pytest ./path/to/test_camera_basler.py --camera_type basler_camera
    """
    return int(pytestconfig.getoption("fps"))


@pytest.fixture(scope="function")
def camera(camera_type, fps):
    if camera_type == "basler_camera":
        cam = BaslerCamera(id=0, fps=fps)
    elif camera_type == "basler_emulated":
        cam = EmulatedBaslerCamera(id=0, fps=fps)
    else:
        raise ValueError("Invalid camera type")

    cam.init()
    yield cam
    cam.close()


class Test_Camera_InitAndStart:
    """Test the ability of the camera to initialize and start without a trigger."""

    def test_start(self, camera):
        camera.start()
        camera.stop()

    def test_grab_one(self, camera):
        camera.set_trigger_mode(
            "no_trigger"
        )  # allows real cameras to caquire without hardware triggers (emulated ones already do)
        camera.start()
        img, _, _ = camera.get_array(timeout=1000)
        assert isinstance(img, np.ndarray)
        camera.stop()


class Test_OpenMultipleCameras:
    """Test how we open multiple cameras so they don't interfere"""

    def test_two_cameras(self, fps, camera_type):

        if camera_type == "basler_camera":
            CamClass = BaslerCamera
        elif camera_type == "basler_emulated":
            CamClass = EmulatedBaslerCamera

        # should default to 0
        cam1 = CamClass(id=0)
        cam2 = CamClass(id=1)
        cam1.init()
        cam2.init()
        cam1.start()
        cam2.start()

        cam1.stop()
        cam2.stop()
        cam1.close()
        cam2.close()


class Test_CameraIDMethods:
    """Test passing the camera id to the camera class."""

    def test_default_device_index(self, camera_type):
        # id should default to 0
        if camera_type == "basler_camera":
            cam = BaslerCamera()
        elif camera_type == "basler_emulated":
            cam = EmulatedBaslerCamera()
        cam.init()
        assert cam.device_index == 0
        cam.close()

    @pytest.mark.parametrize("id", [0, 1])
    def test_set_device_index(self, id, camera_type):
        if camera_type == "basler_camera":
            cam = BaslerCamera(id=id)
        elif camera_type == "basler_emulated":
            cam = EmulatedBaslerCamera(id=id)
        cam.init()
        assert cam.device_index == id
        cam.close()

    def test_id_errs(self):
        with pytest.raises(CameraError):
            _ = BaslerCamera(id="abc")  # no cam with this sn should exist


class Test_FPSWithoutTrigger:
    """Test that we can set the camera fps when we're in non-trigger mode."""

    @pytest.mark.parametrize("_fps", [30, 60, 90, 120])
    def test_fps(self, _fps, camera_type):
        print(camera_type)
        if camera_type == "basler_camera":
            cam = BaslerCamera(id=0, fps=_fps)
        elif camera_type == "basler_emulated":
            pytest.skip("Emulated camera doesn't support fps (seemingly)")

        cam.init()
        cam.set_trigger_mode("no_trigger")

        # Capture two images and check that the time between them is close to the desired fps
        cam.start()
        _, _, ts1 = cam.get_array(get_timestamp=True)
        _, _, ts2 = cam.get_array(get_timestamp=True)
        cam.close()

        # Check that the time between the two images is close to the desired fps
        dt = (ts2 - ts1) / 1e9  # convert to sec
        empirical_fps = 1 / dt
        assert np.isclose(empirical_fps, _fps, atol=0.1)
