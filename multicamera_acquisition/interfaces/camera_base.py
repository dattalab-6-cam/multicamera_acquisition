import numpy as np
from warnings import warn
import yaml


class CameraError(Exception):
    pass


def get_camera(
    fps,
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

    Returns
    -------
    cam : Camera object
        The camera object, specific to the brand.

    """
    if brand == "flir":
        from multicamera_acquisition.interfaces.camera_flir import FlirCamera as Camera

        cam = Camera(index=str(index))

        # cam.init()

        # # set gain
        # cam.GainAuto = "Off"
        # cam.Gain = gain

        # # set exposure
        # cam.ExposureAuto = "Off"
        # cam.ExposureTime = exposure_time

        # # set trigger
        # if trigger == "arduino":
        #     # TODO - many of these settings are not related to the trigger and should
        #     # be redistributed
        #     # TODO - remove hardcoding
        #     cam.AcquisitionMode = "Continuous"
        #     cam.AcquisitionFrameRateEnable = True
        #     max_fps = cam.get_info("AcquisitionFrameRate")["max"]
        #     cam.AcquisitionFrameRate = max_fps
        #     cam.TriggerMode = "Off"
        #     cam.TriggerSource = trigger_line
        #     cam.TriggerOverlap = "ReadOut"
        #     cam.TriggerSelector = "FrameStart"
        #     cam.TriggerActivation = "RisingEdge"
        #     # cam.TriggerActivation = "FallingEdge"
        #     cam.TriggerMode = "On"

        # else:
        #     cam.LineSelector = trigger_line
        #     cam.AcquisitionMode = "Continuous"
        #     cam.TriggerMode = "Off"
        #     cam.TriggerSource = "Software"
        #     cam.V3_3Enable = True
        #     cam.TriggerOverlap = "ReadOut"

        # if roi is not None:
        #     raise NotImplementedError("ROI not implemented for FLIR cameras")

    elif brand == "basler":
        from multicamera_acquisition.interfaces.camera_basler import BaslerCamera 
        cam = BaslerCamera(id=id, name=name, config=config)

    elif brand == "basler_emulated":
        from multicamera_acquisition.interfaces.camera_basler import EmulatedBaslerCamera
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


    elif brand == 'lucid':
        from multicamera_acquisition.interfaces.camera_lucid import (
            LucidCamera as Camera,
        )
        cam = Camera(
            index=str(serial)
        )

    return cam


class BaseCamera(object):
    """
    A class used to encapsulate a Camera.
    Attributes
    ----------
    cam : an abstracted Camera
    running : bool
        True if acquiring images
    camera_attributes : dictionary
        Contains links to all of the camera nodes which are settable
        attributes.
    camera_methods : dictionary
        Contains links to all of the camera nodes which are executable
        functions.
    camera_node_types : dictionary
        Contains the type (as a string) of each camera node.
    lock : bool
        If True, attribute access is locked down; after the camera iacquisition_loopss
        initialized, attempts to set new attributes will raise an error.  This
        is to prevent setting misspelled attributes, which would otherwise
        silently fail to acheive their intended goal.
    intialized : bool
        If True, init() has been called.
    In addition, many more virtual attributes are created to allow access to
    the camera properties.  A list of available names can be found as the keys
    of `camera_attributes` dictionary, and a documentation file for a specific
    camera can be genereated with the `document` method.
    Methods
    -------
    init()
        Initializes the camera.  Automatically called if the camera is opened
        using a `with` clause.
    close()
        Closes the camera and cleans up.  Automatically called if the camera
        is opening using a `with` clause.
    start()
        Start recording images.
    stop()
        Stop recording images.
    get_image()
        Return an image using PySpin's internal format.
    get_array()
        Return an image as a Numpy array.
    get_info(node)
        Return info about a camera node (an attribute or method).
    document()
        Create a Markdown documentation file with info about all camera
        attributes and methods.
    """

    def __init__(self, id=0, name=None, config=None, lock=True, fps=None):
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

        lock : bool (default: True)
            If True, setting new attributes after initialization results in
            an error.
            (Currently only implemented for FLIR cameras)

        fps : int (default: None)
            The desired frame rate for the recording. 
            It is preferred to set this from the config, but this is provided
            for convenience.
        """
        self.id = id
        if isinstance(id, int):
            self.serial_number = None
            self.index = id
            if id > 10:
                warn("Camera index > 10.  Is this correct? Did you mean to use a serial number? If so, use a string instead of an int.")
        elif isinstance(id, str):
            self.serial_number = id
            self.index = None
        elif id is None:
            self.serial_number = None
            self.index = 0
            warn("No camera ID provided.  Using device index 0.")
        else:
            raise ValueError("Invalid camera ID")

        self.config = config
        self.name = name
        self.lock = lock
        self.running = False
        self.model = None
        self.fps = fps

    def _resolve_device_index(self):
        """Given a serial number, find the index of the camera in the system.
        """
        # Get the serial numbers of all connected cameras
        camera_serials, model_names = self._enumerate_cameras()

        # If user wants a specific serial no, find the index of that camera
        if self.serial_number is not None:
            if not np.any([sn == self.serial_number for sn in camera_serials]):
                raise CameraError(f"Camera with serial number {self.id} not found.")
            device_index = camera_serials.index(self.id)
        elif self.index is not None:
            device_index = self.index
        else:
            raise CameraError("Must specify either serial number or index of camera to connect to.")

        self.device_index = device_index
        self.model_name = model_names[device_index]

    def check_config(self, config=None):
        """Check if the camera configuration is valid.
        """
        pass  # defined in each camera subclass

    def init(self):
        """Initializes the camera.  Automatically called if the camera is opened
        using a `with` clause."""
        raise NotImplementedError

    def __enter__(self):
        self.init()
        return self

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
        """Get an image from the camera, and convert it to a numpy array.
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
        raise NotImplementedError

    # def __getattr__(self, attr):
    #    '''Get the value of a camera attribute or method.'''
    #    raise NotImplementedError

    # def __setattr__(self, attr, val):
    #    '''Set the value of a camera attribute.'''
    #    raise NotImplementedError

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

