from multicamera_acquisition.interfaces.camera_base import BaseCamera, CameraError
from multicamera_acquisition.configs.default_basler_config import default_basler_config
from multicamera_acquisition.configs.default_nvc_writer_config import default_nvc_writer_config
from pypylon import pylon
import numpy as np
import os


class BaslerCamera(BaseCamera):

    def __init__(self, id=None, name=None, config_file=None, lock=True):
        """Set up a camera object, instance ready to connect to a camera.
        Parameters
        ----------
        id : int or str (default: 0)
            If an int, the index of the camera to acquire.  
            If a string, the serial number of the camera.

        name: str (default: None)
            The name of the camera in the experiment. For example, "top" or "side2".

        config : path-like str or Path (default: None)
            Path to config file. If None, uses the camera's default config file.

        lock : bool (default: True)
            Not implemented for Baslers, does nothing here.
        """

        # Init the parent class
        super().__init__(id=id, name=name, config_file=config_file, lock=lock)

        # Create the camera object
        self._create_pylon_sys()  # init the pylon API software layer
        self._resolve_device_index()  # sets self.device_index based on the id the user provides

        # Specify that we're not yet running the camera (necessary?)
        self.running = False

        # Load the config
        # (NB: we must configure the basler after opening it, see self.init() and self._configure_basler().)
        if self.config_file is None:
            self.config = BaslerCamera.default_camera_config()  # If no config file is specified, use the default
        else:
            self.load_config(check_if_valid=False)  # could set check to be true by efault? unsure.
            # TODO: this config might be a full recording config, in which case it will contain
            # configs for all cameras in a given recording. Will need to resolve which part of the 
            # config is for this camera (i.e. by serial number or by name)

    @staticmethod
    def default_camera_config():
        return default_basler_config()
    
    @staticmethod
    def default_writer_config():
        return default_nvc_writer_config()

    def _create_pylon_sys(self):
        """
        Creates the following attributes:
            - self.system: the pylon system (pylon.TlFactory.GetInstance())
        """
        # Start the pylon device layer
        self.system = pylon.TlFactory.GetInstance()

    #TODO: make this a static method?
    def _enumerate_cameras(self, behav_on_none="raise"):
        """ Enumerate all Basler cameras connected to the system.
        Called by self._resolve_device_index() in __init__.
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
        di = pylon.DeviceInfo()
        devices = self.system.EnumerateDevices([di,])

        # If no camera is found
        if len(devices) == 0 and behav_on_none == "raise":
            raise RuntimeError("No cameras found.")
        elif len(devices) == 0 and behav_on_none == "pass":
            pass

        # Otherwise, loop through all found devices and get their sn's + model names
        serial_nos = []
        models = []
        for i, device in enumerate(devices):
            camera = pylon.InstantCamera(self.system.CreateDevice(device))
            camera.Open()
            sn = camera.GetDeviceInfo().GetSerialNumber()
            model = camera.GetDeviceInfo().GetModelName()
            camera.Close()
            serial_nos.append(sn)
            models.append(model)

        # Delete the devices instance to free them up (maybe not nec?)
        del devices

        return serial_nos, models

    def init(self):
        """Initializes the camera.  Automatically called if the camera is opened
        using a `with` clause."""

        # Create the pypylon camera object
        self._create_pylon_cam()

        # Open the connection to the camera
        self.cam.Open()

        # Sanity check on serial number
        _sn = self.cam.GetDeviceInfo().GetSerialNumber()
        if self.serial_number is None:
            self.serial_number = _sn
        else:
            assert self.serial_number == _sn, "Unexpected camera serial number mismatch."

        # Record camera model name
        self.model = self.cam.GetDeviceInfo().GetModelName()

        # Configure the camera according to the config file
        self._configure_basler()

    def _create_pylon_cam(self):
        """
        Creates the following attributes:
            - self.cam: the pylon camera (pylon.InstantCamera(self.system.CreateDevice(self.devices[index])))
            - self.model_name: the model name of the camera (self.cam.GetDeviceInfo().GetModelName())
        """
        di = pylon.DeviceInfo()
        devices = self.system.EnumerateDevices([di,])

        # Create the camera with the desired index
        self.cam = pylon.InstantCamera(
            self.system.CreateDevice(devices[self.device_index])
        )

    def _configure_basler(self):
        """ Given the loaded config, set up the basler for acquisition with the config therein.
        """
        # Reset to default settings, for safety (i.e. if user was messing around with the camera and didn't reset the settings)
        self.cam.UserSetSelector.Value = "Default"
        self.cam.UserSetLoad.Execute()

        # Check the config file for any missing or conflicting params 
        assert hasattr(self, "config"), "Must load config file before configuring camera (see load_config())."
        status = self.check_config()
        if status is not None:  # TODO: actually implement telling user what was wrong with the config
            raise CameraError(status)

        # Set gain
        self.cam.GainAuto.SetValue("Off")
        self.cam.Gain.SetValue(self.config["gain"])

        # Set exposure time
        self.cam.ExposureAuto.SetValue("Off")
        self.cam.ExposureTime.SetValue(self.config["exposure"])

        # Set readout mode
        # self.cam.SensorReadoutMode.SetValue(self.config["readout_mode"])

        # Set roi
        roi = self.config["roi"]
        if roi is not None:
            self.cam.Width.SetValue(roi[2])
            self.cam.Height.SetValue(roi[3])
            self.cam.OffsetX.SetValue(roi[0])
            self.cam.OffsetY.SetValue(roi[1])

        # Set trigger
        trigger = self.config["trigger"]
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

    def set_trigger_mode(self, mode):
        """Set the trigger to be hardware or software
        """
        if mode == "hardware":
            # self.cam.AcquisitionMode.SetValue("Continuous")
            self.cam.TriggerMode.SetValue("Off")
            self.cam.TriggerSource.SetValue("Line1")
            self.cam.TriggerSelector.SetValue("FrameStart")
            self.cam.TriggerActivation.SetValue("RisingEdge")
            self.cam.TriggerMode.SetValue("On")
        elif mode == "continuous":
            self.cam.AcquisitionMode.SetValue("Continuous")
            self.cam.TriggerSelector.SetValue("FrameStart")
            self.cam.TriggerMode.SetValue("Off")
            
        else:
            raise ValueError("Trigger mode must be 'hardware' or 'continuous'")

    def start(self):
        "Start recording images."
        self.cam.StartGrabbing(pylon.GrabStrategy_OneByOne)
        self.running = True

    def stop(self):
        "Stop recording images."
        self.cam.StopGrabbing()
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
    return serial_nos, models


class EmulatedBaslerCamera(BaslerCamera):
    """Emulated basler camera for testing.
    """
    from ..tests.interfaces.test_emulated_basler import PylonEmuTestCase

    @staticmethod
    def get_class_and_filter_emulated():
        device_class = "BaslerCamEmu"
        di = pylon.DeviceInfo()
        di.SetDeviceClass(device_class)
        return device_class, [di]

    def __init__(self, id=None, name=None, config_file=None, lock=True):
        super().__init__(id=id, name=name, config_file=config_file, lock=lock)

    def _create_pylon_sys(self):
        """Override the system creation to make an emulated camera
        """

        # Prepare the emulation
        self.device_class, self.device_filter = EmulatedBaslerCamera.get_class_and_filter_emulated()
        num_devices = 1
        os.environ["PYLON_CAMEMU"] = f"{num_devices}"

    def _create_pylon_cam(self):
        """Override the camera creation to make an emulated camera
        """
        self.model_name = "Emulated"
        self.cam = self._create_first()

    def _create_first(self):
        tlf = pylon.TlFactory.GetInstance()
        return pylon.InstantCamera(tlf.CreateFirstDevice(self.device_filter[0]))