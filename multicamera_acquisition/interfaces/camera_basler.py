from multicamera_acquisition.interfaces.camera_base import BaseCamera, CameraError
from pypylon import pylon
import numpy as np


class BaslerCamera(BaseCamera):
    def __init__(self, index=0, lock=True, **kwargs):
        """
        Parameters
        ----------
        index : int or str (default: 0)
            If an int, the index of the camera to acquire.  If a string,
            the serial number of the camera.
        lock : bool (default: True)
            If True, setting new attributes after initialization results in
            an error.
        """
        self.serial_number = index
        self.system = pylon.TlFactory.GetInstance()
        di = pylon.DeviceInfo()
        devices = self.system.EnumerateDevices(
            [
                di,
            ]
        )

        n_devices = len(devices)
        debug: print("Found %d camera(s)" % n_devices)
        camera_serials = np.array([c.GetSerialNumber() for c in devices])

        if n_devices == 0:
            raise CameraError("No cameras detected.")
        if isinstance(index, int):
            self.cam = pylon.InstantCamera(self.system.CreateDevice(devices[index]))
        elif isinstance(index, str):
            if not np.any(camera_serials == index):
                raise CameraError("Camera with serial number %s not found." % index)
            index = np.where(camera_serials == index)[0][0]
            self.cam = pylon.InstantCamera(self.system.CreateDevice(devices[index]))

        del devices

        self.running = False

    def init(self):
        """Initializes the camera.  Automatically called if the camera is opened
        using a `with` clause."""
        self.cam.Open()

        # reset to default settings
        self.cam.UserSetSelector = "Default"
        self.cam.UserSetLoad.Execute()

    def start(self):
        "Start recording images."
        max_recording_hours = 60
        max_recording_frames = max_recording_hours * 60 * 60 * 200
        self.cam.StartGrabbingMax(max_recording_frames)
        self.running = True

    def stop(self):
        "Stop recording images."
        self.cam.Close()
        self.running = False

    def get_image(self, timeout=None):
        """Get an image from the camera.
        Parameters
        ----------
        timeout : int (default: None)
            Wait up to timeout milliseconds for an image if not None.
                Otherwise, wait indefinitely.
        Returns
        -------
        img : PySpin Image
        """
        if timeout is None:
            timeout = 10000
        return self.cam.RetrieveResult(timeout, pylon.TimeoutHandling_ThrowException)

    def get_array(self, timeout=None, get_timestamp=False):
        """Get an image from the camera.
        Parameters
        ----------
        timeout : int (default: None)
            Wait up to timeout milliseconds for an image if not None.
                Otherwise, wait indefinitely.
        get_timestamp : bool (default: False)
            If True, returns timestamp of frame f(camera timestamp)
        Returns
        -------
        img : Numpy array
        tstamp : int
        """
        if self.cam.IsGrabbing() == False:
            raise ValueError("Camera is not set up to grab frames.")

        img = self.get_image(timeout)

        if img.GrabSucceeded():
            img_array = img.Array.astype(np.uint8)
            if get_timestamp:
                tstamp = img.GetTimeStamp()
            else:
                tstamp = None
        else:
            img_array = None
            tstamp = None

        img.Release()

        if get_timestamp:
            return img_array, tstamp
        else:
            return img_array

    def get_info(self, name):
        """Gen information on a camera node (attribute or method).
        Parameters
        ----------
        name : string
            The name of the desired node
        Returns
        -------
        info : dict
            A dictionary of retrieved properties.  *Possible* keys include:
                - `'access'`: read/write access of node.
                - `'description'`: description of node.
                - `'value'`: the current value.
                - `'unit'`: the unit of the value (as a string).
                - `'min'` and `'max'`: the min/max value.
        """
        raise NotImplementedError

    def document(self):
        """Creates a MarkDown documentation string for the camera."""
        raise NotImplementedError
