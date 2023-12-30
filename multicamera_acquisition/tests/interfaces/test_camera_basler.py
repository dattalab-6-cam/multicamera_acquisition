import unittest
import os
from multicamera_acquisition.interfaces.camera_basler import BaslerCamera, CameraError
from pypylon import pylon
import numpy as np

num_devices = 1
os.environ["PYLON_CAMEMU"] = f"{num_devices}"


def get_class_and_filter_emulated():
    device_class = "BaslerCamEmu"
    di = pylon.DeviceInfo()
    di.SetDeviceClass(device_class)
    return device_class, [di]


class PylonEmuTestCase(unittest.TestCase):
    """ Useful base class for emulating a pylon camera
    """
    device_class, device_filter = get_class_and_filter_emulated()

    def create_first(self):
        tlf = pylon.TlFactory.GetInstance()
        return pylon.InstantCamera(tlf.CreateFirstDevice(self.device_filter[0]))


class GrabTestSuite(PylonEmuTestCase):

    """Simple pypylon emulation test.
    Taken directly from: https://github.com/basler/pypylon/tree/master/tests/pylon_tests/emulated
    """

    def test_grabone(self):

        camera = self.create_first()
        camera.Open()
        camera.ExposureTimeAbs.SetValue(10000.0)
        self.assertEqual(10000, camera.ExposureTimeAbs.GetValue())
        result = camera.GrabOne(1000)
        actual = list(result.Array[0:20, 0])
        expected = [actual[0] + i for i in range(20)]
        self.assertEqual(actual, expected)
        camera.Close()

    def test_grab(self):
        countOfImagesToGrab = 5
        imageCounter = 0
        camera = self.create_first()
        camera.Open()
        camera.ExposureTimeAbs.SetValue(10000.0)
        self.assertEqual(10000, camera.ExposureTimeAbs.GetValue())
        camera.StartGrabbingMax(countOfImagesToGrab)
        # Camera.StopGrabbing() is called automatically by the RetrieveResult() method
        # when c_countOfImagesToGrab images have been retrieved.
        while camera.IsGrabbing():
            # Wait for an image and then retrieve it. A timeout of 5000 ms is used.
            grabResult = camera.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)
            # Image grabbed successfully?
            if grabResult.GrabSucceeded():
                # Access the image data.
                imageCounter = imageCounter + 1
                self.assertEqual(1024, grabResult.Width)
                self.assertEqual(1040, grabResult.Height)
                img = grabResult.Array
            grabResult.Release()
        self.assertEqual(countOfImagesToGrab, imageCounter)
        camera.Close()


class BaslerCameraTestCase(unittest.TestCase):
    """Test the basler camera subclas
    """

    def setUp(self):
        self.cam = BaslerCamera(id=0)

    def test_a_init(self):
        self.cam.init()

    def test_b_start(self):
        self.cam.start()
        self.cam.stop()

    def test_c_grab_one(self):
        self.cam.init()  # have to run init() after stop() currently; not my fave way of doing it.
        self.cam.set_trigger_mode("continuous")  # allows cam to caquire without hardware triggers
        self.cam.start()
        img = self.cam.get_array(timeout=1000)
        self.assertEqual(type(img), np.ndarray)
        self.cam.stop()

    def tearDown(self):
        self.cam.close()  # basically same as .stop() but also deletes the cam attr
        return super().tearDown()
    

class BaslerCamera_VariousIDMethods_TestCase(unittest.TestCase):
    """Test the basler camera subclas
    """

    def setUp(self):
        pass

    def test_a_id_int(self):
        
        # should default to 0
        cam = BaslerCamera(id=0)
        self.assertEqual(cam.id, 0)
        cam.close()

        cam = BaslerCamera(id=0)
        self.assertEqual(cam.id, 0)
        cam.close()

    def test_b_id_errs(self):
        self.assertRaises(CameraError, BaslerCamera, id="0")  # id is a string whose sn doesn't exist, should raise error

        # todo: figure out the serial no of a basler that's connected and test that

    def tearDown(self):
        return super().tearDown()


class EmulatedBaslerCameraTestCase(unittest.TestCase):
    """Test the emulated basler camera subclas
    """

    def setUp(self):
        self.cam = BaslerCamera(id=0)

    def test_a_init(self):
        self.cam.init()

    def test_b_start(self):
        self.cam.start()
        self.cam.stop()

    def test_c_grab_one(self):
        self.cam.init()  # have to run init() after stop() currently; not my fave way of doing it.
        self.cam.set_trigger_mode("continuous")  # allows cam to caquire without hardware triggers
        self.cam.start()
        img = self.cam.get_array(timeout=1000)
        self.assertEqual(type(img), np.ndarray)
        self.cam.stop()

    def tearDown(self):
        self.cam.close()  # basically same as .stop() but also deletes the cam attr
        return super().tearDown()
