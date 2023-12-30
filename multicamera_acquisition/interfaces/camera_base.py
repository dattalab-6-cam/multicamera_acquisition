import yaml


class CameraError(Exception):
    pass


def get_camera(
    brand="flir",
    serial_number=None,
    index=0,
    config_file=None,
):
    """Get a camera object.
    Parameters
    ----------
    brand : string (default: 'flir')
        The brand of camera to use.  Currently only 'flir' is supported. If
        'flir', the software PySpin is used. if 'basler', the software pypylon
        is used.

    serial_number : int or str (default: None)
        The serial number of the camera. Ultimately used to find the index
        of the camera in the software layer.
        TAKES PRECEDENCE OVER INDEX.

    index : int (default: 0)
        The index of the camera to acquire, in a list of devices
        enumerated by the software layer of the camera API.

    config_file : string (default: None)
        Path to a config file.  If None, the default config file for the given
        camera brand will be used.

    Returns
    -------
    cam : Camera object
        The camera object, specific to the brand.

    """
    if brand == "flir":
        from multicamera_acquisition.interfaces.camera_flir import FlirCamera as Camera

        cam = Camera(index=str(index))

        cam.init()

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
        cam = BaslerCamera(index=index, config_file=config_file)
        cam.init()

    elif brand == "basler_emulated":
        from multicamera_acquisition.interfaces.camera_basler import EmulatedBaslerCamera
        cam = EmulatedBaslerCamera()
        cam.init()

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
        cam.init()

    return cam

class BaseCamera(object):
    """
    A class used to encapsulate a Camera.
    Attributes
    ----------
    cam : PySpin Camera
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

    def __init__(self, index=0, config_file=None):
        """Create a camera instance connected to a camera, without actually "open"ing it (i.e. without starting the connection).
        Parameters
        ----------
        index : int or str (default: 0)
            If an int, the index of the camera to acquire.  If a string,
            the serial number of the camera.
        config : path-like str or Path (default: None)
            Path to config file. If None, uses the camera's default config file.
        """
        self.index = index
        self.config_file = config_file

    def save_config(self):
        """Save the current camera configuration to a YAML file.
        """
        with open(self.config_file, 'w') as f:
            yaml.dump(self.config, f, default_flow_style=False)

    def load_config(self, check_if_valid=False):
        """Load a camera configuration YAML file.
        """
        with open(self.config_file, 'r') as f:
            config = yaml.load(f)
        self.config = config

        if check_if_valid:
            self.check_config()

    def update_config(self, new_config):
        """Update the config file.

        Parameters
        ----------
        new_config: dict
            Dictionary of new config values
        """
        def recursive_update(config, updates):
            for key, value in updates.items():
                if key in config and isinstance(config[key], dict):
                    # If the key is a dictionary, recurse
                    recursive_update(config[key], value)
                else:
                    # Otherwise, update the value directly
                    config[key] = value
            return config
        
        tmp_config = recursive_update(self.config, new_config)
        if self.check_config(tmp_config):
            self.config = tmp_config
            self.save_config()

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

