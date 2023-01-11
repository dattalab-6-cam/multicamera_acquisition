import numpy as np


class CameraError(Exception):
    pass


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

    def __init__(self, index=0, lock=True):
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

