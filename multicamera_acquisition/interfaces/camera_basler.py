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
        # debug: print("Found %d camera(s)" % n_devices)
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

    def get_info(self, name=None):
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


def enumerate_basler_cameras(behav_on_none="raise"):
    """ Enumerate all Basler cameras connected to the system.
    
    Parameters
    ----------
    behav_on_none : str (default: 'raise')
        If 'raise', raises an error if no cameras are found.
        If 'pass', returns None if no cameras are found.

    Returns
    -------
    cameras : list of strings
        A list of serial numbers of all connected cameras.
    """

    # Instantiate an object for the camera finder
    tl_factory = pylon.TlFactory.GetInstance()
    devices = tl_factory.EnumerateDevices()

    # If no camera is found
    if len(devices) == 0 and behav_on_none == "raise":
        raise RuntimeError("No cameras found.")
    elif len(devices) == 0 and behav_on_none == "pass":
        return None

    # Otherwise, loop through all found devices 
    # and print their serial numbers
    serial_nos = []
    models = []
    for i, device in enumerate(devices):
        camera = pylon.InstantCamera(tl_factory.CreateDevice(device))
        camera.Open()
        sn = camera.GetDeviceInfo().GetSerialNumber()
        model = camera.GetDeviceInfo().GetModelName()
        print(f"Camera {i+1}:")
        print(f"\tSerial Number: {sn}")
        print(f"\tModel: {model}")
        camera.Close()
        serial_nos.append(sn)
        models.append(model)

    # Return a list of serial numbers
    return  serial_nos, models


class EmulatedBaslerCamera(BaslerCamera):
    """Emulated basler camera for testing.
    """
    from ..tests.interfaces.test_camera_basler import PylonEmuTestCase

    # Override the init method to use the emulated camera
    def __init__(self, **kwargs):
        """
        Parameters
        ----------
        """
        self.serial_number = "Emulated"
        self.cam = self.PylonEmuTestCase.create_first()
        self.running = False

    def init(self):
        """Initializes the camera.  Automatically called if the camera is opened
        using a `with` clause."""
        self.cam.Open()

        # reset to default settings
        self.cam.UserSetSelector = "Default"
        self.cam.UserSetLoad.Execute()

        # set to do a grayscale grating drift
        self.cam.TestPattern.Value = "Testimage2"
