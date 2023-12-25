""" This camera object can inherit from the same genreal class as 
basler and flir, but with some pecularities.
- Azures should await a trigger from the arduino before starting
- The camera grabs multiple images. RGB, IR, and depth.
- ???

"""

from multicamera_acquisition.interfaces.camera_base import BaseCamera, CameraError
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
import subprocess


class AzureCamera(BaseCamera):
    def __init__(self, name, azure_index, serial_number=0, lock=True, **kwargs):
        """
        Parameters
        ----------
        serial_number : int or str (default: 0)
            If an int, the serial_number of the camera to acquire.  If a string,
            the serial number of the camera.
        lock : bool (default: True)
            If True, setting new attributes after initialization results in
            an error.
        """

        self.serial_number = serial_number
        self.name = name

        # camera_indexes = get_camera_indexes({self.name: self.serial_number})

        camera_config = Config(
            color_resolution=ColorResolution.OFF,
            depth_mode=DepthMode.NFOV_UNBINNED,
            synchronized_images_only=False,
            wired_sync_mode=WiredSyncMode.SUBORDINATE,
            subordinate_delay_off_master_usec=serial_number*160,
        )

        self.cam = PyK4A(camera_config, device_id=azure_index)
        self.timeout_warning_flag = False

    def init(self):
        """Initializes the camera.  Automatically called if the camera is opened
        using a `with` clause."""

        # initialize K4A object

        pass

    def start(self):
        "Start recording images."
        self.cam.start()

    def stop(self):
        "Stop recording images."
        try:
            self.cam.stop()
            # self.cam.close()
        except Exception as e:
            warnings.warn(e)

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
    if not count:
        print("No Azures available")
        return
    print(f"Available Azures: {count}")
    idx_to_sn ={}
    for device_id in range(count):
        device = PyK4A(device_id=device_id)
        device.open()
        print(f"{device_id}: {device.serial}")
        idx_to_sn[device_id] = device.serial
        device.close()
    return idx_to_sn
