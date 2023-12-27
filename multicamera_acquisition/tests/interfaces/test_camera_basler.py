import unittest
import os
import sys

num_devices = 1
os.environ["PYLON_CAMEMU"] = f"{num_devices}"
from pypylon import pylon

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