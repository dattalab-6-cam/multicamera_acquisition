"""Adapted from https://github.com/soorajsknair93/PureThermal2-FLIR-Lepton3.5-Interfacing-Python"""

import time
import logging
import numpy as np
from queue import Queue
from multicamera_acquisition.interfaces.camera_base import BaseCamera, CameraError
from .purethermal_uvctypes import *


def list_purethermal_serial_numbers():
    """List the serial numbers of all PureThermal cameras connected to the system.

    Enumerates UVC devices that match PT_USB_VID and PT_USB_PID.
    These are configured to seek Lepton3.5 cameras with the PureThermal 2 board.

    Returns
    -------
    list of str
    """
    serials = []
    ctx = POINTER(uvc_context)()
    libuvc.uvc_init(byref(ctx), 0)
    devs_ptr = POINTER(POINTER(uvc_device))()
    res = libuvc.uvc_find_devices(ctx, byref(devs_ptr), PT_USB_VID, PT_USB_PID, None)
    if res == 0:
        try:
            i = 0
            while devs_ptr[i]:
                dev = devs_ptr[i]
                devh = POINTER(uvc_device_handle)()
                res = libuvc.uvc_open(dev, byref(devh))
                if res == 0:
                    sn = create_string_buffer(32)
                    call_extension_unit(devh, SYS_UNIT_ID, 3, sn, 8)
                    serial_number = sn.raw.rstrip(b'\x00').hex()
                    libuvc.uvc_close(devh)
                else:
                    serial_number = None
                serials.append(serial_number)
                i += 1
        finally:
            libuvc.uvc_free_device_list(devs_ptr, 1)
    libuvc.uvc_exit(ctx)
    return serials


class PureThermalCamera(BaseCamera):
    FPS = 9
    BUF_SIZE = 2

    def __init__(self, id=None, name=None, config=None):
        """Encapsulates a connection to a pure thermal camera.

        Parameters
        ----------
        id : int or str (default: 0)
            If an int, the index of the camera to acquire.
            If a string, the serial number of the camera.
        name : str (default: None)
            A human-readable name for the camera (e.g., 'top', 'side').
        config : dict (default: None)
            A dictionary of camera parameters; uses default_camera_config() if None.
        """
        super().__init__(id=id, name=name, config=config, fps=self.FPS)

        # set self.device_index based on the id the user provides
        self._resolve_device_index() 

        # load a default config if needed (mostly for testing, least common)
        if self.config is None:
            self.config = PureThermalCamera.default_camera_config().copy()

        # initialize other variables
        self.q = Queue(self.BUF_SIZE)
        self.PTR_PY_FRAME_CALLBACK = CFUNCTYPE(None, POINTER(uvc_frame), c_void_p)(self._py_frame_callback)
        self.ctx = POINTER(uvc_context)()
        self.devh = POINTER(uvc_device_handle)()
        self.ctrl = uvc_stream_ctrl()


    @staticmethod
    def default_camera_config():
        """Generate a default config for a PureThermal camera."""
        return {
            "brand": "purethermal",
            "display": {"display_frames": False, "display_range": (0, 255)},
            "ffc_mode": "auto", # options are {"auto", "start", "none"},
        }

    @staticmethod
    def default_writer_config(fps, writer_type="ffmpeg"):
        from multicamera_acquisition.writer import FFMPEG_Writer
        writer_config = FFMPEG_Writer.default_writer_config(fps, vid_type="mono16")
        return writer_config

    def _enumerate_cameras(self):
        """Enumerate all PureThermal cameras connected to the system.

        Called by self._resolve_device_index() in super().__init__().

        Returns
        -------
        (serial_nos, models) : tuple of list of strings
            Lists of serial numbers and models of all connected cameras.
        """
        serial_nos = list_purethermal_serial_numbers()
        models = ["PureThermal"] * len(serial_nos)
        return serial_nos, models

    # TODO
    def init(self):
        """
        Initializes, opens, and configures the camera.

        This is automatically called if the camera is opened
        using a `with` clause.
        """
        # try to find the logger
        try:
            self.logger = logging.getLogger(f"{self.name}_acqLoop")
        except AttributeError:
            self.logger = logging.getLogger()

        
        # open and configure camera
        self.logger.debug("Commence opening PureThermal camera")
        try:
            # initialize uvc context
            self.logger.debug("Initializing uvc context")
            libuvc.uvc_init(byref(self.ctx), 0)

            # open camera
            self.logger.debug("Opening camera with device index %s", self.device_index)
            devs_ptr = POINTER(POINTER(uvc_device))()
            res = libuvc.uvc_find_devices(self.ctx, byref(devs_ptr), PT_USB_VID, PT_USB_PID, 0)
            libuvc.uvc_open(devs_ptr[self.device_index], byref(self.devh))
            libuvc.uvc_free_device_list(devs_ptr, 1)

            # configure camera
            if self.config["ffc_mode"] == "auto":
                set_auto_ffc(self.devh)
            else:
                self.logger.debug("setting manual ffc")
                set_manual_ffc(self.devh)
                if self.config["ffc_mode"] == "start":
                    perform_manual_ffc(self.devh)

            frame_formats = uvc_get_frame_formats_by_guid(self.devh, VS_FMT_GUID_Y16)
            libuvc.uvc_get_stream_ctrl_format_size(self.devh, byref(self.ctrl), UVC_FRAME_FORMAT_Y16,
                                                    frame_formats[0].wWidth, frame_formats[0].wHeight,
                                                    int(1e7 / frame_formats[0].dwDefaultFrameInterval))
            self.logger.debug(f"Set frame format for {self.serial_number}: width = {frame_formats[0].wWidth}")
            self.logger.debug(f"Set frame format for {self.serial_number}: height = {frame_formats[0].wHeight}")
            self.logger.debug(f"Set frame format for {self.serial_number}: interval = {frame_formats[0].dwDefaultFrameInterval}")

        except:
            libuvc.uvc_close(self.devh)
            libuvc.uvc_exit(self.ctx)
            raise CameraError(f"Error opening pure thermal camera {self.serial_number}")



    def _py_frame_callback(self, frame, userptr):
        self.logger.debug("Received frame from PureThermal camera %s", self.serial_number)
        array_pointer = cast(frame.contents.data, POINTER(c_uint16 * (frame.contents.width * frame.contents.height)))
        data = np.frombuffer(
            array_pointer.contents, dtype=np.dtype(np.uint16)
        ).reshape(frame.contents.height, frame.contents.width)
        if frame.contents.data_bytes != (2 * frame.contents.width * frame.contents.height):
            return
        if not self.q.full():
            self.q.put(data)

    def start(self):
        """Start streaming images"""
        libuvc.uvc_start_streaming(self.devh, byref(self.ctrl), self.PTR_PY_FRAME_CALLBACK, None, 0)
        self.logger.debug("Started streaming PureThermal camera %s", self.serial_number)
        self.running = True

    def stop(self):
        """Stop streaming images"""
        libuvc.uvc_stop_streaming(self.devh)
        self.running = False

    def close(self):
        """Stops grabbing, closes the camera, and deletes the camera object.
        Automatically called if the camera is opening using a `with` clause.
        """
        self.stop()
        libuvc.uvc_close(self.devh)
        libuvc.uvc_exit(self.ctx)

    # TODO: generate timestamp in _py_frame_callback
    def get_array(self, timeout=None, get_timestamp=False):
        """
        Retrieves a radiometric image from the PureThermal camera as a NumPy array.

        Parameters
        ----------
        timeout : float or None
            How long to wait for a frame (seconds). None means block indefinitely.
        get_timestamp : bool
            If True, also return a timestamp for the captured frame.

        Returns
        -------
        frame : numpy.ndarray
            The captured image data.
        timestamp : int or None
            Returns a timestamp if get_timestamp=True; otherwise None.
        """
        if timeout is None:
            timeout = 10000

        timestamp = time.time() if get_timestamp else None
        img_array = np.copy(self.q.get(True, timeout))
        linestatus = None
        return img_array, linestatus, timestamp


def cKelvin_to_celsius(arr):
    """Convert from units of 0.01 Kelvin to Celsius."""
    return (arr - 27315) / 100.0
    

def celsius_to_cKelvin(arr):
    """Convert from Celsius to units of 0.01 Kelvin."""
    return (arr * 100.0) + 27315