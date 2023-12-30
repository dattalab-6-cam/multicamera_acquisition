
from multicamera_acquisition.interfaces.camera_basler import (
    BaslerCamera, CameraError
)
import numpy as np
# import os
import pytest
import unittest


@pytest.mark.real_camera
class BaslerCamera_InitAndStart_TestCase(unittest.TestCase):
    """Test the basler camera subclas
    """

    def setUp(self):
        """ Called before each test
        """
        self.cam = BaslerCamera(id=0)
        self.cam.init()

    def test_a_start(self):
        self.cam.start()
        self.cam.stop()

    def test_b_grab_one(self):
        self.cam.set_trigger_mode("continuous")  # allows cam to caquire without hardware triggers
        self.cam.start()
        img = self.cam.get_array(timeout=1000)
        self.assertEqual(type(img), np.ndarray)
        self.cam.stop()

    def tearDown(self):
        self.cam.close()  # basically same as .stop() but also deletes the cam attr
        return super().tearDown()


@pytest.mark.real_camera
class BaslerCamera_VariousIDMethods_TestCase(unittest.TestCase):
    """Test the basler camera subclas
    """

    def setUp(self):
        pass

    def test_a_id_int(self):
        # should default to 0
        cam = BaslerCamera()
        cam.init()
        self.assertEqual(cam.device_index, 0)
        cam.close()

        cam = BaslerCamera(id=0)
        cam.init()
        self.assertEqual(cam.device_index, 0)
        cam.close()

    def test_b_id_errs(self):
        self.assertRaises(CameraError, BaslerCamera, id="0")  # id is a string whose sn doesn't exist, should raise error

    def tearDown(self):
        return super().tearDown()
