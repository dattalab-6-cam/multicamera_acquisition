# define the base camera

import numpy as np
import struct


def get_camera(
    brand="flir", serial_number=None, exposure_time=2000, gain=15, trigger="arduino"
):
    """Get a camera object.
    Parameters
    ----------
    brand : string (default: 'flir')
        The brand of camera to use.  Currently only 'flir' is supported. If
        'flir', the software PySpin is used. if 'basler', the software pypylon
        is used.
    serial_number : string (default: None)
        The serial number of the camera to use.  If None, the first camera
        found will be used.
    exposure_time : int (default: 2000)
        The exposure time in microseconds.
    gain : int (default: 15)
        The gain for the camera.
    Returns
    -------
    cam : Camera object
        The camera object, specific to the brand.

    """
    if brand == "flir":
        from multicamera_acquisition.interfaces.camera_flir import FlirCamera as Camera

        cam = Camera(index=str(serial_number))

        cam.init()

        cam.GainAuto = "Off"
        cam.Gain = gain
        cam.ExposureAuto = "Off"
        cam.ExposureTime = exposure_time

        if trigger == "arduino":
            cam.AcquisitionMode = "Continuous"
            cam.AcquisitionFrameRateEnable = True
            max_fps = cam.get_info("AcquisitionFrameRate")["max"]
            cam.AcquisitionFrameRate = max_fps
            cam.TriggerMode = "Off"
            cam.TriggerSource = "Line3"
            cam.TriggerOverlap = "ReadOut"
            cam.TriggerSelector = "FrameStart"
            cam.TriggerActivation = "RisingEdge"
            cam.TriggerMode = "On"

        else:
            cam.LineSelector = "Line2"
            cam.V3_3Enable = True

    if brand == "basler":
        raise NotImplementedError

    return cam
