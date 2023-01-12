# define the base camera

import numpy as np
import struct


def get_camera(
    brand="flir", serial_number=None, exposure_time=2000, gain=12, trigger="arduino"
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

        # set gain
        cam.GainAuto = "Off"
        cam.Gain = gain

        # set exposure
        cam.ExposureAuto = "Off"
        cam.ExposureTime = exposure_time

        # set trigger
        if trigger == "arduino":
            # TODO - many of these settings are not related to the trigger and should
            # be redistributed
            # TODO - remove hardcoding
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
        from multicamera_acquisition.interfaces.camera_basler import (
            BaslerCamera as Camera,
        )

        cam = Camera(index=str(serial_number))
        cam.init()

        # set gain
        cam.cam.GainAuto.SetValue("Off")
        cam.cam.Gain.SetValue(gain)

        # Tset exposure time
        cam.cam.ExposureAuto.SetValue("Off")
        cam.cam.ExposureTime.SetValue(exposure_time)

        # set trigger
        if trigger == "arduino":
            # see https://github.com/basler/pypylon/issues/119
            # set external trigger / input line
            # Acquisition mode
            cam.cam.AcquisitionMode.SetValue("Continuous")
            # cam.cam.AcquisitionFrameRateEnable.SetValue('On')
            max_fps = cam.cam.AcquisitionFrameRate.GetMax()
            cam.cam.AcquisitionFrameRate.SetValue(max_fps)
            cam.cam.TriggerMode.SetValue("Off")
            cam.cam.TriggerSource.SetValue("Line3")
            cam.cam.TriggerSelector.SetValue("FrameStart")
            cam.cam.TriggerActivation.SetValue("RisingEdge")
            cam.cam.TriggerMode.SetValue("On")

        else:
            # TODO - implement software trigger
            raise NotImplementedError

    return cam
