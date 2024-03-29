import logging
import warnings

import numpy as np

from multicamera_acquisition.interfaces.camera_base import BaseCamera, CameraError

try:
    from pyk4a import (
        ColorResolution,
        Config,
        DepthMode,
        PyK4A,
        WiredSyncMode,
        connected_device_count,
    )
except ImportError:
    warnings.warn("pyk4a not installed.  Azure cameras will not be available.")


class AzureCamera(BaseCamera):
    def __init__(self, id=0, name=None, config=None):
        """Create an instance of an Azure Kinect camera, without actually "open"ing it (i.e. without starting the connection).
        Parameters
        ----------
        id : int or str (default: 0)
            If an int, the index of the camera to acquire.
            If a string, the serial number of the camera.
        name: str (default: None)
            The name of the camera in the experiment. For example, "top" or "side2".
        config : dict (default: None)
            A dictionary of config params.
            If None, uses the default config.
        """

        # Init the parent class
        super().__init__(id=id, name=name, config=config)

        # Resolve which device to use
        self._resolve_device_index()  # sets self.device_index based on the id the user provides

        # Load the config
        # (NB: we must configure the Azure *before* opening it, contrary to the other cameras [or so it seems from our existing code])
        # If no config file is specified, use the default (mostly for testing, least common)
        if self.config is None:
            self.config = AzureCamera.default_camera_config().copy()

        # TODO: add a check that the config is valid

    def __repr__(self):
        """Returns a string representation of the camera object."""
        # python info
        address = hex(id(self))
        basic_info = f'<{self.__class__.__module__ + "." + self.__class__.__qualname__} object at {address}>'

        # TODO: ADD more camera-specific info
        attrs_to_list = ["serial_number", "device_index"]
        cam_info = "Basler Camera: \n" + "\n\t".join(
            [f"{attr}: {getattr(self, attr)}" for attr in attrs_to_list]
        )

        return basic_info + "\n" + cam_info

    @staticmethod
    def default_camera_config():
        """A default config dict for an Azure Kinect camera."""

        # also to include: name, sn, model, firmware, acq mode (eg nfov unbinned)
        config = {
            "fps": 30,
            "depth_mode": "NFOV_UNBINNED",  # "narrow field of view, unbinned"
            "synchronized_images_only": False,
            "sync_mode": "subordinate",
            "subordinate_delay_off_master_usec": 0,
            "brand": "azure",
            "display": {"display_frames": False, "display_range": (0, 255)},
        }
        return config

    # TODO: check what the azure writer is
    @staticmethod
    def default_writer_config(fps, writer_type="ffmpeg"):
        from multicamera_acquisition.writer import FFMPEG_Writer

        writer_config = FFMPEG_Writer.default_writer_config(fps, vid_type="ir")
        return writer_config

    def init(self):
        """Initialize the camera."""

        # Try to find the logger
        try:
            self.logger = logging.getLogger(f"{self.name}_acqLoop")
        except AttributeError:
            self.logger = logging.getLogger()

        # Create the config object
        camera_config = self._get_azure_config()

        # Create the camera object
        self.cam = PyK4A(camera_config, device_id=self.device_index)

        # self.timeout_warning_flag = False  # unused?

    def _get_azure_config(self):
        """Create a PyK4a config object using the config dict."""
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
            subordinate_delay_off_master_usec = config[
                "subordinate_delay_off_master_usec"
            ]
            assert (
                config["subordinate_delay_off_master_usec"] % 160 == 0
            ), f"subordinate_delay_off_master_usec must be a multiple of 160 but was {config['subordinate_delay_off_master_usec']}"

        elif config["sync_mode"] == "master":
            wsm = (
                WiredSyncMode.SUBORDINATE
            )  # if you set this to master, it won't listen for triggers. For us "master" means first subordinate to receive a trigger.
            cr = ColorResolution.RES_720P
            subordinate_delay_off_master_usec = 0
        elif config["sync_mode"] == "true_master":
            wsm = WiredSyncMode.MASTER
            cr = ColorResolution.RES_720P
            subordinate_delay_off_master_usec = 0
        else:
            raise ValueError(
                f"Invalid sync_mode: {config['sync_mode']} (must be 'subordinate' or 'master')"
            )

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
        camera_index_dict = enumerate_azure_cameras()
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
            If True, returns color image; else, None.
        get_timestamp : bool (default: False)
            If True, returns timestamp of frame f(camera timestamp); else, None.

        Returns
        -------
        depth : np.ndarray
            The depth image.
        ir : np.ndarray
            The ir image.
        color : np.ndarray
            The color image.
        tstamp : int
            The timestamp of the frame.
        """

        def ir16_to_uint8(ir):
            return (np.clip(ir, 0, 1275) / 5).astype(np.uint8)

        # Grab image
        capture = self.get_image(timeout)

        # Grab depth and ir
        # TODO ensure depth and ir are actually captured
        depth = capture.depth.astype(np.uint16)
        ir = ir16_to_uint8(capture.ir)

        timestamp = None
        color = None
        if get_timestamp:
            timestamp = capture._ir_timestamp_usec
        if get_color:
            color = capture.color

        return depth, ir, color, timestamp

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


def enumerate_azure_cameras():
    """https://github.com/etiennedub/pyk4a/blob/master/example/devices.py"""
    count = connected_device_count()
    if not count:
        # print("No Azures available")
        return {}
    # print(f"Available Azures: {count}")
    idx_to_sn_dict = {}
    for device_id in range(count):
        device = PyK4A(device_id=device_id)
        device.open()
        # print(f"{device_id}: {device.serial}")
        idx_to_sn_dict[device_id] = device.serial
        device.close()
    return idx_to_sn_dict
