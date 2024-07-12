import logging
import traceback
import uvc

from multicamera_acquisition.interfaces.camera_base import BaseCamera, CameraError


class UVCCamera(BaseCamera):
    def __init__(
        self,
        id=None,
        name=None,
        config=None,
        fps=None,
    ):
        """Encapsulates a connection to a UVC camera.

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
            The desired fps for the camera.

        logger_queue : multiprocessing.Queue (default: None)
            A queue to which the camera will write log messages.

        logging_level : int (default: logging.DEBUG)
            The logging level to use for the camera.
        """

        # Init the parent class
        super().__init__(id=id, name=name, config=config, fps=fps)

        # Create the camera object
        self._create_uvc_sys()  # init the uvc API software layer

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
                UVCCamera.default_camera_config().copy()
            )  # If no config file is specified, use the default

    def __repr__(self):
        """Returns a string representation of the camera object."""

        # Typical python info
        address = hex(id(self))
        basic_info = f'<{self.__class__.__module__ + "." + self.__class__.__qualname__} object at {address}>'

        # Add camera-specific info
        attrs_to_list = ["name", "serial_number", "device_index", "model", "running"]
        cam_info = "UVC Camera: \n" + "\n\t".join(
            [f"{attr}: {getattr(self, attr)}" for attr in attrs_to_list]
        )

        return basic_info + "\n" + cam_info

    @staticmethod
    def default_camera_config():
        """Generate a default config for a UVC camera."""
        config = {
            "roi": None,  # ie use the entire roi
            "gain": 50,
            "gamma": 340,
            "exposure": 50, # 1/200*10000 at 200 Hz
            "brand": "uvc",
            "exposure_mode": 1, # 1 is manual mode
            "exposure_priority": 0, # 0 is fixed frame rate
            "brightness": 2,
            "contrast": 100,
            "frame_size": (640, 400),
            "fps": 60,
            "display": {
                "display_frames": False,
                "display_range": (0, 255),
            }
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

    def _create_uvc_sys(self):
        """Creates a self.system attribute with the uvc device layer"""
        self.system = uvc

    def _enumerate_cameras(self, behav_on_none="raise"):
        """Enumerate all UVC cameras connected to the system.

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
        devices = self.system.device_list()

        # If no camera is found
        if len(devices) == 0 and behav_on_none == "raise":
            raise RuntimeError("No cameras found.")
        elif len(devices) == 0 and behav_on_none == "pass":
            pass

        # Otherwise, loop through all found devices and get their sn's + model names
        serial_nos = []
        models = []
        for device in devices:
            serial_nos.append(device["serialNumber"])
            models.append(device["idProduct"])

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

        try:
            # Create the pyuvc camera object
            self.logger.debug("Creating cam and opening connection to cam...")
            self._create_uvc_cam()
            self.logger.debug("Opened connection to cam.")

            # Configure the camera
            self.logger.debug("Configuring camera...")
            self._configure_uvc()
        except Exception as e:
            # show the entire traceback
            self.logger.error(traceback.format_exc())
            raise e

        self.initialized = True

    def _create_uvc_cam(self):
        """Creates the uvc camera object, open it.

        Creates the following attributes:
            - self.cam: the uvc camera (uvc.Capture(self.devices[index]['uid']))
            - self.model_name: the model name of the camera (devices[index]['idProduct'])
        """
        devices = uvc.device_list()

        try:
            self.cam = self.system.Capture(devices[self.device_index]['uid'])
        except Exception as e:
            raise RuntimeError(
                f"(Real) UVC camera with id {self.device_index} and serial {self.serial_number} failed to open: {e}"
            )

        self.model_name = devices[self.device_index]['idProduct']

    def _configure_uvc(self):
        """Given the loaded config, set up the uvc for acquisition with the config therein."""

        # Check the config file for any missing or conflicting params
        assert hasattr(
            self, "config"
        ), "Must load config file before configuring camera (see load_config())."
        status = self.check_config()
        if (
            status is not None
        ):  # TODO: actually implement telling user what was wrong with the config
            raise CameraError(status)

        controls = {self.cam.controls[i].display_name: self.cam.controls[i] for i in range(len(self.cam.controls))}

        # Set gain
        controls['Gain'].value = self.config["gain"]

        # Set gamma
        controls['Gamma'].value = self.config["gamma"]

        # Set exposure
        controls['Auto Exposure Mode'].value = self.config["exposure_mode"]
        controls['Auto Exposure Priority'].value = self.config["exposure_priority"]
        controls['Absolute Exposure Time'].value = self.config["exposure"]

        # Set brightness
        controls['Brightness'].value = self.config["brightness"]

        # Set contrast
        controls['Contrast'].value = self.config["contrast"]

        # Set the frame size
        self.cam.frame_size = self.config["frame_size"]

        # Set the frame rate
        self.cam.frame_rate = self.config["fps"]
    
    def start(self):
        "Start recording images."
        self.running = True

    def stop(self):
        "Stop recording images."
        self.running = False

    def close(self):
        """Stops grabbing, closes the camera, and deletes the camera object.
        Automatically called if the camera is opening using a `with` clause.
        """
        self.stop()
        self.cam.close()
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
        img : image
        """
        if timeout is None:
            timeout = 10000
        
        frame = self.cam.get_frame(timeout=timeout/1000.0) # timeout is in seconds for pyuvc

        if not frame.data_fully_received:
            self.logger.warning("Frame not fully received.")

        return frame.gray

    def get_array(self, timeout=None, get_timestamp=False, get_linestatus=False):
        """Get an image from the camera.

        Parameters
        ----------
        timeout : int (default: None)
            Wait up to timeout milliseconds for an image if not None.
                Otherwise, wait indefinitely.

        get_timestamp : bool (default: False)
            If True, returns timestamp of frame (from the camera's clock, in microseconds).
            If False, this value is None.

        get_linestatus : bool (default: False)
            If True, returns the line status of the camera.
            If False, this value is None.

        Returns
        -------
        img : Numpy array
            The image as a numpy array.

        line_status : int
            The line status of the camera, if get_linestatus=True; else, None.

        tstamp : int ()
            The timestamp of the frame, if get_timestamp=True; else, None.
        """

        if timeout is None:
            timeout = 10000

        frame = self.cam.get_frame_robust()
        # frame = self.cam.get_frame(timeout=timeout/1000.0) # timeout is in seconds for pyuvc

        if not frame.data_fully_received:
            self.logger.warning("Frame not fully received.")

        # img_array = frame.gray.T
        img_array = frame.gray
        timestamp = frame.timestamp if get_timestamp else None
        line_status = None

        # self.logger.debug(f"Frame shape: {img_array.shape} ")
        # self.logger.debug(f"Frame img type: {type(img_array)}")

        return img_array, line_status, timestamp


def enumerate_uvc_cameras(behav_on_none="raise"):
    """Enumerate all UVC cameras connected to the system.

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
    devices = uvc.device_list()

    # If no camera is found
    if len(devices) == 0 and behav_on_none == "raise":
        raise RuntimeError("No cameras found.")
    elif len(devices) == 0 and behav_on_none == "pass":
        pass

    # Otherwise, loop through all found devices and get their sn's + model names
    serial_nos = []
    models = []
    for device in devices:
        serial_nos.append(device["serialNumber"])
        models.append(device["idProduct"])

    # Delete the devices instance to free them up (maybe not nec?)
    del devices

    return serial_nos, models
