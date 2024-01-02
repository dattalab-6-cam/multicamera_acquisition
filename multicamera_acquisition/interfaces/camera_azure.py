""" This camera object can inherit from the same genreal class as 
basler and flir, but with some pecularities.
- Azures should await a trigger from the arduino before starting
- The camera grabs multiple images. RGB, IR, and depth.
- ???

"""

from multicamera_acquisition.interfaces.camera_base import BaseCamera, CameraError
from multicamera_acquisition.config.default_azure_config import default_azure_config
from pyk4a import (
    PyK4A,
    Config,
    ColorResolution,
    DepthMode,
    WiredSyncMode,
    connected_device_count
)
import numpy as np
import warnings


class AzureCamera(BaseCamera):
    def __init__(self, id=0, name=None, config_file=None, lock=True):
        """Create an instance of an Azure Kinect camera, without actually "open"ing it (i.e. without starting the connection).
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
            If True, setting new attributes after initialization results in
            an error.
            (Currently only implemented for FLIR cameras)
        """

        # Init the parent class
        super().__init__(id=id, name=name, config_file=config_file, lock=lock)

        # Resolve which device to use
        self._resolve_device_index()  # sets self.device_index based on the id the user provides

        # Load the config
        # (NB: we must configure the Azure *before* opening it, contrary to the other cameras [or so it seems from our existing code])
        if self.config_file is None:
            self.config = default_azure_config()  # If no config file is specified, use the default
            # TODO: save the default config to a file once we know where acquisition is happening.
        else:
            self.load_config(check_if_valid=False)  # could set check to be true by efault? unsure.
        self._load_config(check_if_valid=True)  # this is the only chance we'll have to check if it's valid, so do it here

    def init(self):
        """Initialize the camera.
        """
        # Create the config object
        camera_config = self._get_azure_config()

        # Create the camera object
        self.cam = PyK4A(camera_config, device_id=self.device_index)

        # self.timeout_warning_flag = False  # unused?

    def _get_azure_config(self):
        """Create a PyK4a config object using the config dict.
        """
        config = self.config

        # Set depth sensor acq mode
        if config["depth_mode"] == "NFOV_UNBINNED":
            dm = DepthMode.NFOV_UNBINNED
        else:
            raise NotImplementedError

        # Set sync mode and other dependent params
        if config["sync_mode"] == "subordinate":
            cr = ColorResolution.OFF
            wsm = WiredSyncMode.SUBORDINATE
            subordinate_delay_off_master_usec = config["subordinate_delay_off_master_usec"]

        elif config["sync_mode"] == "master":
            wsm = WiredSyncMode.SUBORDINATE  # if you set this to master, it won't listen for triggers. For us "master" means first subordinate to receive a trigger.
            cr = ColorResolution.RES_720P
            subordinate_delay_off_master_usec = 0
        else:
            raise ValueError(f"Invalid sync_mode: {config['sync_mode']} (must be 'subordinate' or 'master')")

        camera_config = Config(
            color_resolution=cr,
            depth_mode=dm,
            synchronized_images_only=config["synchronized_images_only"],
            wired_sync_mode=wsm,
            subordinate_delay_off_master_usec=subordinate_delay_off_master_usec,
        )

        return camera_config

    def _enumerate_cameras(self, behav_on_none="raise"):
        """Enumerate all Azures connected to the system.

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
        camera_index_dict = get_camera_indexes()
        serial_nos = list(camera_index_dict.values())
        if len(camera_index_dict) == 0:
            if behav_on_none == "raise":
                raise CameraError("No cameras found.")
            else:
                return [], []

        return serial_nos, []

    def start(self):
        "Start recording images."
        self.cam.start()  # will wait for a trigger if in subordinate mode

    def stop(self):
        "Stop recording images."
        if self.cam.is_running:
            self.cam.stop()
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
        img : K4A Image
        """

        if timeout is None:
            timeout = 10000

        return self.cam.get_capture(timeout=timeout)

    def get_array(self, timeout=None, get_color=False, get_timestamp=False):
        """Get an image from the camera.
        Parameters
        ----------
        timeout : int (default: None)
            Wait up to timeout milliseconds for an image if not None.
                Otherwise, wait indefinitely.
        get_color : bool (default: False)
            If True, returns color image
        get_timestamp : bool (default: False)
            If True, returns timestamp of frame f(camera timestamp)
        Returns
        -------
        img : Numpy array
        tstamp : int
        """

        def ir16_to_uint8(ir):
            return (np.clip(ir, 0, 1275) / 5).astype(np.uint8)

        # grab image
        capture = self.get_image(timeout)

        # grab depth and ir
        # TODO ensure depth and ir are actually captured
        depth = capture.depth.astype(np.uint16)
        ir = ir16_to_uint8(capture.ir)

        if get_timestamp:
            tstamp = capture._ir_timestamp_usec

        if get_color:
            color = capture.color
            return depth, ir, color, tstamp
        else:
            return depth, ir, tstamp

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


def get_camera_indexes():
    """https://github.com/etiennedub/pyk4a/blob/master/example/devices.py
    """
    count = connected_device_count()
    idx_to_sn_dict = {}
    for device_id in range(count):
        device = PyK4A(device_id=device_id)
        device.open()
        # print(f"{device_id}: {device.serial}")
        idx_to_sn_dict[device_id] = device.serial
        device.close()
    return idx_to_sn_dict
