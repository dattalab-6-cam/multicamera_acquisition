import logging
import os
import time

import numpy as np
from pypylon import pylon
from pypylon._genicam import RuntimeException

from multicamera_acquisition.interfaces.camera_base import BaseCamera, CameraError


class BaslerCamera(BaseCamera):
    def __init__(
        self,
        id=None,
        name=None,
        config=None,
        fps=None,
    ):
        """Encapsulates a connection to a Basler camera.

        Parameters
        ----------
        id : int or str (default: 0)
            If an int, the index of the camera to acquire.
            If a string, the serial number of the camera.

        name: str (default: None)
            The name of the camera in the experiment. For example, "top" or "side2".

        config : dict (default: None)
            A dictionary of config params.
            If config is None, uses the camera's default config file.

        fps : int (default: None)
            Current deprecated for Basler cameras.  Baslers are enabled for their max fps by default.
            If performing non-triggered acquisition, the desired fps for the camera.

        logger_queue : multiprocessing.Queue (default: None)
            A queue to which the camera will write log messages.

        logging_level : int (default: logging.DEBUG)
            The logging level to use for the camera.
        """

        # Init the parent class
        super().__init__(id=id, name=name, config=config, fps=fps)

        # Create the camera object
        self._create_pylon_sys()  # init the pylon API software layer

        # Resolve the device index (ie, find which camera to connect to)
        if self.serial_number is not None and self.device_index is None:
            self._resolve_device_index()  # sets self.device_index based on the id the user provides
        elif self.serial_number is None and self.device_index is None:
            raise ValueError(
                "Camera unexpectedly has no serial number or device index."
            )

        # Load a default config if needed (mostly for testing, least common)
        if self.config is None:
            self.config = (
                BaslerCamera.default_camera_config().copy()
            )  # If no config file is specified, use the default

        if (fps is not None or "fps" in self.config.keys()) and (
            "trigger_mode" in self.config.keys()
            and self.config["trigger_mode"] == "microcontroller"
        ):
            self.logger.warn(
                "Providing fps for Baslers in triggered mode is deprecated and generally not necessary."
            )

    def __repr__(self):
        """Returns a string representation of the camera object."""

        # Typical python info
        address = hex(id(self))
        basic_info = f'<{self.__class__.__module__ + "." + self.__class__.__qualname__} object at {address}>'

        # Add camera-specific info
        attrs_to_list = ["name", "serial_number", "device_index", "model", "running"]
        cam_info = "Basler Camera: \n" + "\n\t".join(
            [f"{attr}: {getattr(self, attr)}" for attr in attrs_to_list]
        )

        return basic_info + "\n" + cam_info

    @staticmethod
    def default_camera_config():
        """Generate a default config for a Basler camera."""
        config = {
            "roi": None,  # ie use the entire roi
            "gain": 6,
            "gamma": 1.0,
            "exposure": 1000,
            "brand": "basler",
            "display": {
                "display_frames": False,
                "display_range": (0, 255),
            },
            "trigger": {
                "trigger_type": "microcontroller",
                "acquisition_mode": "Continuous",
                "trigger_source": "Line2",
                "trigger_selector": "FrameStart",
                "trigger_activation": "RisingEdge",
            },
        }
        return config

    @staticmethod
    def default_writer_config(fps, writer_type="ffmpeg", gpu=None):
        if writer_type == "nvc" and gpu is not None:
            from multicamera_acquisition.writer import NVC_Writer

            writer_config = NVC_Writer.default_writer_config(fps, gpu=gpu).copy()
        elif writer_type == "ffmpeg":
            from multicamera_acquisition.writer import FFMPEG_Writer

            writer_config = FFMPEG_Writer.default_writer_config(
                fps, vid_type="ir", gpu=gpu
            ).copy()
        return writer_config

    def _create_pylon_sys(self):
        """Creates a self.system attribute with the pylon device layer (pylon.TlFactory.GetInstance())"""
        self.system = pylon.TlFactory.GetInstance()

    def _enumerate_cameras(self, behav_on_none="raise"):
        """Enumerate all Basler cameras connected to the system.

        Called by self._resolve_device_index() in super().__init__().

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
        devices = self.system.EnumerateDevices(
            [
                di,
            ]
        )

        # If no camera is found
        if len(devices) == 0 and behav_on_none == "raise":
            raise RuntimeError("No cameras found.")
        elif len(devices) == 0 and behav_on_none == "pass":
            pass

        # Otherwise, loop through all found devices and get their sn's + model names
        serial_nos = []
        models = []
        for i, device in enumerate(devices):
            try:
                camera = pylon.InstantCamera(self.system.CreateDevice(device))
            except RuntimeException:
                # TODO: what is the proper way to check if we can open a camera, rather than catching the error?
                serial_nos.append(None)
                models.append(None)
                continue
            camera.Open()
            sn = str(camera.GetDeviceInfo().GetSerialNumber())
            model = camera.GetDeviceInfo().GetModelName()
            camera.Close()
            serial_nos.append(sn)
            models.append(model)

        # Delete the devices instance to free them up (maybe not nec?)
        del devices

        return serial_nos, models

    def init(self):
        """Initializes, opens, and configures the camera.

        This is automatically called if the camera is opened
        using a `with` clause.
        """

        # Try to find the logger within the acqLoop process
        try:
            self.logger = logging.getLogger(f"{self.name}_acqLoop")
        except AttributeError:
            self.logger = logging.getLogger()

        self.logger.debug(f"Initializing camera {self.name}...")

        # Create the pypylon camera object
        self.logger.debug(f"Creating cam")
        self._create_pylon_cam()

        # Open the connection to the camera
        self.logger.debug(f"Opening connection to cam")
        self.cam.Open()

        # Sanity check on serial number
        _sn = self.cam.GetDeviceInfo().GetSerialNumber()
        if self.serial_number is None:
            self.serial_number = _sn
        else:
            assert (
                self.serial_number == _sn
            ), "Unexpected camera serial number mismatch."

        # Record camera model name
        self.model = self.cam.GetDeviceInfo().GetModelName()

        # Configure the camera according to the config file
        self._configure_basler()

        self.initialized = True

    def _create_pylon_cam(self):
        """Creates the pylon camera object, without opening it.

        Creates the following attributes:
            - self.cam: the pylon camera (pylon.InstantCamera(self.system.CreateDevice(self.devices[index])))
            - self.model_name: the model name of the camera (self.cam.GetDeviceInfo().GetModelName())
        """
        di = pylon.DeviceInfo()
        devices = self.system.EnumerateDevices(
            [
                di,
            ]
        )

        try:
            self.cam = pylon.InstantCamera(
                self.system.CreateDevice(devices[self.device_index])
            )
        except Exception as e:
            raise RuntimeError(
                f"(Real) Basler camera with id {self.device_index} and serial {self.serial_number} failed to open: {e}"
            )

    def _configure_basler(self):
        """Given the loaded config, set up the basler for acquisition with the config therein."""
        # Reset to default settings, for safety (i.e. if user was messing around with the camera and didn't reset the settings)
        self.cam.UserSetSelector.Value = "Default"
        self.cam.UserSetLoad.Execute()

        # Check the config file for any missing or conflicting params
        assert hasattr(
            self, "config"
        ), "Must load config file before configuring camera (see load_config())."
        status = self.check_config()
        if (
            status is not None
        ):  # TODO: actually implement telling user what was wrong with the config
            raise CameraError(status)

        # Set gain
        self.cam.GainAuto.SetValue("Off")
        self.cam.Gain.SetValue(self.config["gain"])

        # enable reading GPIO states
        self.cam.ChunkModeActive.Value = True
        self.cam.ChunkSelector.Value = "LineStatusAll"
        self.cam.ChunkEnable.Value = True

        # Set gamma
        self.cam.Gamma.SetValue(self.config["gamma"])

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
        if trigger["trigger_type"] == "microcontroller":
            self.cam.AcquisitionMode.SetValue(trigger["acquisition_mode"])
            max_fps = self.cam.AcquisitionFrameRate.GetMax()
            self.cam.AcquisitionFrameRate.SetValue(max_fps)
            self.cam.TriggerMode.SetValue("Off")  # why have to set to off here?
            self.cam.TriggerSource.SetValue(trigger["trigger_source"])
            self.cam.TriggerSelector.SetValue(trigger["trigger_selector"])
            self.cam.TriggerActivation.SetValue(trigger["trigger_activation"])
            self.cam.TriggerMode.SetValue("On")

        elif trigger["trigger_type"] == "software":
            # TODO - implement software trigger
            # TODO - this error isn't raised in the main thread. how to propagate it?
            raise NotImplementedError(
                "Software trigger not implemented for Basler cameras"
            )
        elif trigger["trigger_type"] == "no_trigger":
            self.set_trigger_mode("no_trigger")
        else:
            raise ValueError("Trigger must be 'microcontroller' or 'software'")

    def check_config(self):
        """Check for some common issues with Basler configs."""

        # Ensure user doesnt request emulated cameras with microcontroller trigger mode
        if (
            self.config["trigger"]["trigger_type"] == "microcontroller"
            and self.config["brand"] == "basler_emulated"
        ):
            raise ValueError(
                "Cannot use microcontroller trigger with emulated cameras."
            )

    def set_trigger_mode(self, mode):
        """Shortcut method to quickly change the camera's trigger settings.

        Parameters
        ----------
        mode : str
            The trigger mode to use.  Must be one of:
                - 'microcontroller': use the microcontroller trigger
                - 'no_trigger': acquire continuously without requiring a trigger.
        """
        if mode == "microcontroller":
            self.cam.AcquisitionMode.SetValue("Continuous")
            self.cam.TriggerMode.SetValue("Off")
            self.cam.TriggerSource.SetValue("Line2")
            self.cam.TriggerSelector.SetValue("FrameStart")
            self.cam.TriggerActivation.SetValue("RisingEdge")
            self.cam.TriggerMode.SetValue("On")
        elif mode == "no_trigger":
            if not hasattr(self, "fps") or self.fps is None:
                self.logger.warn(
                    "No fps specified for Basler camera running in no_trigger mode. Defaulting to 30 fps."
                )
                self.fps = 30
            self.cam.AcquisitionMode.SetValue("Continuous")
            self.cam.TriggerMode.SetValue("Off")
            self.cam.AcquisitionFrameRateEnable.SetValue(True)
            self.cam.AcquisitionFrameRate.SetValue(float(self.fps))

        else:
            raise ValueError("Trigger mode must be 'arduino' or 'no_trigger'")

    def start(self):
        "Start recording images."
        self.cam.StartGrabbing(pylon.GrabStrategy_OneByOne)
        self.running = True

    def stop(self):
        "Stop recording images."
        self.cam.StopGrabbing()
        self.running = False

    def close(self):
        """Stops grabbing, closes the camera, and deletes the camera object.
        Automatically called if the camera is opening using a `with` clause.
        """
        self.stop()
        self.cam.Close()
        del self.cam

    def get_image(self, timeout=None):
        """Get an image from the camera.

        Parameters
        ----------
        timeout : int (default: None)
            Wait up to timeout milliseconds for an image if not None.
                Otherwise, wait indefinitely.

        Returns
        -------
        img : PyPylon image (?)
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
            If True, returns timestamp of frame (from the camera's clock, in microseconds).

        Returns
        -------
        img : Numpy array
            The image as a numpy array.

        tstamp : int
            The timestamp of the frame, if get_timestamp=True.
        """
        if self.cam.IsGrabbing() is False:
            raise ValueError("Camera is not set up to grab frames.")

        img = self.get_image(timeout)

        img_array = None
        tstamp = None

        if img.GrabSucceeded():
            img_array = img.Array.astype(np.uint8)
            line_status = img.ChunkLineStatusAll.Value
            # self.logger.debug(f"{line_status}")
            if get_timestamp:
                tstamp = img.GetTimeStamp()

        img.Release()

        if get_timestamp:
            return img_array, line_status, tstamp
        else:
            return img_array, line_status


def enumerate_basler_cameras(behav_on_none="raise"):
    """Enumerate all Basler cameras connected to the system.

    Parameters
    ----------
    behav_on_none : str (default: 'raise')
        If 'raise', raises an error if no cameras are found.
        If 'pass', returns None if no cameras are found.

    Returns
    -------
    serial_nos, models : tuple

        serial_nos: list of serial numbers of all connected cameras.

        models: list of model names of all connected cameras.
    """

    # Instantiate an object for the camera finder
    tl_factory = pylon.TlFactory.GetInstance()
    devices = tl_factory.EnumerateDevices()

    # If no camera is found
    if len(devices) == 0 and behav_on_none == "raise":
        raise RuntimeError("No cameras found.")
    elif len(devices) == 0 and behav_on_none == "pass":
        return None, None

    # Otherwise, loop through all found devices
    serial_nos = []
    models = []
    for i, device in enumerate(devices):
        camera = pylon.InstantCamera(tl_factory.CreateDevice(device))
        camera.Open()
        sn = camera.GetDeviceInfo().GetSerialNumber()
        model = camera.GetDeviceInfo().GetModelName()
        camera.Close()
        del camera
        serial_nos.append(sn)
        models.append(model)

    # Destroy the devices instance to free them up (maybe not nec?)
    del devices
    del tl_factory

    # Return a list of serial numbers
    return serial_nos, models


class EmulatedBaslerCamera(BaslerCamera):
    """Emulated basler camera for testing."""

    @staticmethod
    def get_emulated_filter():
        """Returns a device filter that can be passed to pylon.TlFactory.GetInstance().EnumerateDevices()."""
        device_class = "BaslerCamEmu"
        di = pylon.DeviceInfo()
        di.SetDeviceClass(device_class)
        return [di]

    def __init__(
        self,
        id=None,
        name=None,
        config=None,
        fps=None,
    ):
        super().__init__(id=id, name=name, config=None, fps=fps)

        if config is None:
            self.config = EmulatedBaslerCamera.default_camera_config().copy()
        else:
            self.config = config

    def _create_pylon_sys(self):
        """Override the system creation to make an emulated camera"""
        try:
            current_num_devices = int(os.environ["PYLON_CAMEMU"])
            # Add a device if necessary
            if self.device_index >= current_num_devices:
                current_num_devices = (
                    self.device_index + 1
                )  # since device index is 0-indexed
                os.environ["PYLON_CAMEMU"] = str(current_num_devices)
        except KeyError:
            current_num_devices = (
                self.device_index + 1
            )  # If no emulated devices exist, make one
            os.environ["PYLON_CAMEMU"] = str(current_num_devices)

        self.num_devices = current_num_devices

        # Sleep to allow the env var to update (??)
        time.sleep(0.1)

        # Prepare the emulation
        self.device_filter = EmulatedBaslerCamera.get_emulated_filter()
        self.system = pylon.TlFactory.GetInstance()

    def _enumerate_cameras(self, behav_on_none="raise"):
        """Implemented for compatibility with BaslerCamera.

        Emulated Baslers should be accessed by their index (i.e. id=0, id=1, etc),
        so there is no need to enumerate them.
        """
        return [None] * self.num_devices, [None] * self.num_devices

    def _create_pylon_cam(self):
        """Override the camera creation to make an emulated camera"""
        devices = self.system.EnumerateDevices(self.device_filter)
        try:
            self.cam = pylon.InstantCamera(
                self.system.CreateDevice(devices[self.device_index])
            )
        except Exception as e:
            raise RuntimeError(
                f"(Emulated) Basler camera with id {self.device_index} and serial {self.serial_number} failed to open: {e}"
            )
        self.model_name = "Emulated"

    def set_trigger_mode(self, mode):
        """Override the set trigger mode for emulated cameras, since they don't receive triggers."""
        pass

    @staticmethod
    def default_camera_config():
        # TODO: is there a way to get this to inherit gracefully?
        config = {
            "roi": None,  # ie use the entire roi
            "gain": 6,
            "exposure": 1000,
            "brand": "basler_emulated",
            "display": {"display_frames": False, "display_range": (0, 255)},
            "trigger": {
                "trigger_type": "no_trigger",
            },
        }
        return config
