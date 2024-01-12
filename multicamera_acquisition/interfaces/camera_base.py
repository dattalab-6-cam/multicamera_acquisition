import logging
import numpy as np
import yaml

from multicamera_acquisition.logging_utils import setup_child_logger


class CameraError(Exception):
    pass


def get_camera(
    brand="basler",
    id=0,
    name=None,
    config=None,
):
    """Get a camera object.

    Parameters
    ----------
    fps : int
        The desired frame rate for the camera.

    brand : string (default: 'flir')
        The brand of camera to use.  Currently only 'flir' is supported. If
        'flir', the software PySpin is used. if 'basler', the software pypylon
        is used.

    id: int or str (default: 0)
        If an int, the index of the camera to acquire.
        If a string, the serial number of the camera.

    config : dict (default: None)
        A dictionary of config values.
        If config is None, uses the camera's default config file.

    process_name : str (default: None)
        The name of the process that will use this camera.  This is used to
        create a logger for the camera.

    Returns
    -------
    cam : Camera object
        The camera object, specific to the brand.

    """
    if brand == "basler":
        from multicamera_acquisition.interfaces.camera_basler import BaslerCamera

        cam = BaslerCamera(id=id, name=name, config=config)

    elif brand == "basler_emulated":
        from multicamera_acquisition.interfaces.camera_basler import (
            EmulatedBaslerCamera,
        )

        cam = EmulatedBaslerCamera(id=id, name=name, config=config)

    elif brand == "azure":
        from multicamera_acquisition.interfaces.camera_azure import AzureCamera

        if "name" in kwargs:
            name = kwargs["name"]
        else:
            raise ValueError("Azure camera requires name")

        cam = AzureCamera(
            serial_number=str(serial), name=name, azure_index=kwargs["azure_index"]
        )

    elif brand == "lucid":
        raise NotImplementedError("Lucid camera not yet implemented in refactored branch.")

    return cam


class BaseCamera(object):
    """
    A class used to encapsulate a camera.

    Attributes
    ----------
    elf.config = config
        self.name = name
        self.running = False
        self.initialized = False
        self.model = None
        self.fps = fps

    config : dict
        A dictionary of config values.

    name : str
        The name of the camera in the experiment. For example, "top" or "side2".

    model: str
        The model of the camera.

    intialized : bool
        If True, init() has been called successfully.
        If False, init() has not been called, or it failed, or the camera has been closed
        and it must be re-init'd.

    fps : int
        The desired frame rate for the camera. Deprecated for Baslers (not required) + Azures (fixed at 30).

    cam : an abstracted Camera
        The camera object, specific to the brand.

    running : bool
        True if acquiring images

    """

    def __init__(
        self, 
        id=0, 
        name=None, 
        config=None, 
        fps=None, 
    ):
        """Set up a camera object,instance ready to connect to a camera.
        Parameters
        ----------
        id : int or str (default: 0)
            If an int, the index of the camera to acquire.
            If a string, the serial number of the camera.

        name: str (default: None)
            The name of the camera in the experiment. For example, "top" or "side2".

        config : dict (default: None)
            A dictionary of config values.
            If config is None, uses the camera's default config file.

        fps : int (default: None)
            The desired frame rate for the recording.
            It is preferred to set this from the config, but this is provided
            for convenience.

        logger_queue : multiprocessing.Queue (default: None)
            A queue to which the camera will write log messages.

        logging_level : int (default: logging.DEBUG)
            The logging level to use for the camera.
        """

        if isinstance(id, int):
            self.serial_number = None
            self.device_index = id
            if id > 10:
                pass
                # self.logger.warn(
                #     "Camera index > 10.  Is this correct? Did you mean to use a serial number? If so, use a string instead of an int."
                # )
        elif isinstance(id, str):
            self.serial_number = id
            self.device_index = None
        elif id is None:
            self.serial_number = None
            self.device_index = 0
            # self.logger.warn("No camera ID provided.  Using device index 0.")
        else:
            raise ValueError("Invalid camera ID, must be int or str.")

        self.config = config
        self.name = name
        self.running = False
        self.initialized = False
        self.model = None

        if (
            fps is None
            and self.config is not None
            and "fps" in self.config
            and self.config["fps"] is not None
        ):
            self.fps = self.config["fps"]
        elif fps is not None:
            self.fps = fps

    def _resolve_device_index(self):
        """Resolve the device index of the camera.  This is used to connect to
        the camera via the enumeration of devices in the system.
        """
        # Get the serial numbers of all connected cameras
        camera_serials, model_names = self._enumerate_cameras()

        # If user wants a specific serial no, find the index of that camera
        if self.serial_number is not None:
            if not np.any([sn == self.serial_number for sn in camera_serials]):
                raise CameraError(
                    f"Camera with serial number {self.serial_number} not found."
                )
            device_index = camera_serials.index(self.serial_number)
            self.device_index = device_index
        else:
            raise CameraError(
                "Must specify either serial number or index of camera to connect to."
            )

        self.model_name = model_names[device_index]

    def check_config(self, config=None):
        """Check if the camera configuration is valid."""
        pass  # defined in each camera subclass

    def init(self):
        """Initializes the camera.  Automatically called if the camera is opened
        using a `with` clause."""
        raise NotImplementedError

    def close(self):
        """Closes the camera and cleans up.  Automatically called if the camera
        is opening using a `with` clause."""

        self.stop()
        del self.cam
        self.camera_attributes = {}
        self.camera_methods = {}
        self.camera_node_types = {}
        self.initialized = False
        # self.system.ReleaseInstance()

    def __enter__(self):
        self.init()
        return self

    def __exit__(self, type, value, traceback):
        self.close()

    def start(self):
        "Start recording images."
        raise NotImplementedError

    def stop(self):
        "Stop recording images."
        raise NotImplementedError

    def get_image(self, timeout=None):
        raise NotImplementedError

    def get_array(self, timeout=None, get_chunk=False, get_timestamp=False):
        raise NotImplementedError

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
        # generate a markdown doc from the camera attributes
