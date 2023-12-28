from multicamera_acquisition.interfaces.camera_base import BaseCamera, CameraError
from multicamera_acquisition.configs.default_basler_config import default_basler_config
from pypylon import pylon
import numpy as np


class BaslerCamera(BaseCamera):

    def __init__(self, index=0, config_file=None):
        """Create a camera instance connected to a camera, without actually ".open()"ing it (i.e. without starting the connection).
        Parameters
        ----------
        index : int or str (default: 0)
            If an int, the index of the camera to acquire.  
            If a string, the serial number of the camera.

        config : path-like str or Path (default: None)
            Path to config file. If None, uses the camera's default config file.
        """
        
        # Init the parent class
        super().__init__(index=index, config_file=config_file)

        ### SET UP THE CAMERA ###
        # Start the pylon device layer
        self.system = pylon.TlFactory.GetInstance()
        di = pylon.DeviceInfo()
        self.devices = self.system.EnumerateDevices([di,])

        # Get the serial numbers of all connected cameras
        camera_serials, model_names = self._enumerate_cameras()

        # If user wants a specific serial no, find the index of that camera
        if isinstance(index, str):
            if not np.any(camera_serials == index):
                raise CameraError("Camera with serial number %s not found." % index)
            index = camera_serials.index(index)

        # Create the camera with the desired index
        self.cam = pylon.InstantCamera(self.system.CreateDevice(self.devices[index]))
        self.model_name = model_names[index]

        # Delete the device attribute (to allow other camera objects to use it? unclear.)
        delattr(self, "devices")

        # Specify that we're not yet running the camera (necessary?)
        self.running = False

        # If no config file is specified, use the default
        if self.config_file is None:
            self.config = default_basler_config()
            # TODO: save the default config to a file once we know where acquisition is happening.

    def _enumerate_cameras(self, behav_on_none="raise"):
        """ Enumerate all Basler cameras connected to the system.
        
        Parameters
        ----------
        behav_on_none : str (default: 'raise')
            If 'raise', raises an error if no cameras are found.
            If 'pass', returns None if no cameras are found.

        Returns
        -------
        (serial_nos, models) : tuple of list of strings
            Lists of serial numbers and models of all connected cameras.
        """
       
        # If no camera is found
        if len(self.devices) == 0 and behav_on_none == "raise":
            raise RuntimeError("No cameras found.")
        elif len(self.devices) == 0 and behav_on_none == "pass":
            return None

        # Otherwise, loop through all found devices and get their sn's + model names
        serial_nos = []
        models = []
        for i, device in enumerate(self.devices):
            camera = pylon.InstantCamera(self.system.CreateDevice(device))
            camera.Open()
            sn = camera.GetDeviceInfo().GetSerialNumber()
            model = camera.GetDeviceInfo().GetModelName()
            camera.Close()
            serial_nos.append(sn)
            models.append(model)

        return  serial_nos, models

    def init(self):
        """Initializes the camera.  Automatically called if the camera is opened
        using a `with` clause."""
        
        # Open the connection to the camera
        self.cam.Open()

        # House keeping
        self.serial_number = self.cam.GetDeviceInfo().GetSerialNumber()
        self.model = self.cam.GetDeviceInfo().GetModelName()

        # Reset to default settings, for safety (i.e. if user was messing around with the camera and didn't reset the settings)
        self.cam.UserSetSelector = "Default"
        self.cam.UserSetLoad.Execute()

        # Configure the camera according to the config file
        self._configure_basler()

    def _configure_basler(self):
        """ Load in the config file and set up the basler for acquisition with the config therein.
        """

        # Check the config file for any missing or conflicting params 
        status = self.check_config()
        if status is not None:  # TODO: actually implement telling user what was wrong with the config
            raise CameraError(status)

        # Set gain
        self.cam.GainAuto.SetValue("Off")
        self.cam.Gain.SetValue(self.config["camera"]["gain"])

        # Set exposure time
        self.cam.ExposureAuto.SetValue("Off")
        self.cam.ExposureTime.SetValue(self.config["camera"]["exposure"])

        # Set readout mode
        self.cam.SensorReadoutMode.SetValue(self.config["camera"]["readout_mode"])

        # Set roi
        roi = self.config["camera"]["roi"]
        if roi is not None:
            self.cam.Width.SetValue(roi[2])
            self.cam.Height.SetValue(roi[3])
            self.cam.OffsetX.SetValue(roi[0])
            self.cam.OffsetY.SetValue(roi[1])

        # Set trigger
        trigger = self.config["camera"]["trigger"]
        if trigger["short_name"] == "arduino":
            self.cam.AcquisitionMode.SetValue(trigger["acquisition_mode"])
            # self.cam.AcquisitionFrameRateEnable.SetValue('On')
            max_fps = self.cam.AcquisitionFrameRate.GetMax()
            self.cam.AcquisitionFrameRate.SetValue(max_fps)
            self.cam.TriggerMode.SetValue("Off")  # why have to set to off here?
            self.cam.TriggerSource.SetValue(trigger["trigger_source"])
            self.cam.TriggerSelector.SetValue(trigger["trigger_selector"])
            self.cam.TriggerActivation.SetValue(trigger["trigger_activation"])
            self.cam.TriggerMode.SetValue("On")

        elif trigger["short_name"] == "software":
            # TODO - implement software trigger
            # TODO - this error isn't raised in the main thread. how to propagate it?
            raise NotImplementedError("Software trigger not implemented for Basler cameras")
        else:
            raise ValueError("Trigger must be 'arduino' or 'software'")

    def start(self):
        "Start recording images."
        max_recording_hours = 60
        max_recording_frames = max_recording_hours * 60 * 60 * 200  # ??
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

        img_array = None
        tstamp = None
        
        if img.GrabSucceeded():
            img_array = img.Array.astype(np.uint8)
            if get_timestamp:
                tstamp = img.GetTimeStamp()

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
        self.cam = self.PylonEmuTestCase().create_first()
        self.running = False

    def init(self):
        """Initializes the camera.  Automatically called if the camera is opened
        using a `with` clause."""
        self.cam.Open()

        # reset to default settings
        # self.cam.UserSetSelector = "Default"
        # self.cam.UserSetLoad.Execute()

        # set to do a grayscale grating drift
        # self.cam.TestPattern.Value = "TestImage2"
