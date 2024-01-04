import struct
import numpy as np
import warnings
import sys
import glob
import serial
import logging


def packIntAsLong(value):
    """Packs a python 4 byte integer to an arduino long
    Parameters
    ----------
    value : int
        A 4 byte integer
    Returns
    -------
    packed : bytes
        A 4 byte long
    """
    return struct.pack("i", value)


def wait_for_serial_confirmation(
    arduino, expected_confirmation, seconds_to_wait=5, timeout_duration_s=0.1
):
    confirmation = None
    for i in range(int(seconds_to_wait / timeout_duration_s)):
        confirmation = arduino.readline().decode("utf-8").strip("\r\n")
        if confirmation == expected_confirmation:
            logging.info("Confirmation recieved: {}".format(confirmation))
            break
        else:
            if len(confirmation) > 0:
                logging.info(
                    'PySerial: "{}" confirmation expected, got "{}"". Trying again.'.format(
                        expected_confirmation, confirmation
                    )
                )
    if confirmation != expected_confirmation:
        raise ValueError(
            'Confirmation "{}" signal never recieved from Arduino'.format(
                expected_confirmation
            )
        )
    return confirmation


def find_serial_ports():
    """Lists serial port names, across OS's.
    https://stackoverflow.com/questions/12090503/listing-available-com-ports-with-python

        :raises EnvironmentError:
            On unsupported or unknown platforms
        :returns:
            A list of the serial ports available on the system
    """
    if sys.platform.startswith("win"):
        ports = ["COM%s" % (i + 1) for i in range(256)]
    elif sys.platform.startswith("linux") or sys.platform.startswith("cygwin"):
        # this excludes your current terminal "/dev/tty"
        ports = glob.glob("/dev/tty[A-Za-z]*")
    elif sys.platform.startswith("darwin"):
        ports = glob.glob("/dev/tty.*")
    else:
        raise EnvironmentError("Unsupported platform")

    result = []
    for port in ports:
        try:
            s = serial.Serial(port)
            s.close()
            result.append(port)
        except (OSError, serial.SerialException):
            pass
    return result

class Arduino(object):
    def __init__(self, fps):
        self.fps = fps
        return None
    def generate_basler_frametimes(self, nazures=2, azure_offset=10, basler_offset=10, camera='top'):

        valid_fps = [30, 60, 90, 120, 150]
        assert self.fps in valid_fps, ValueError(f'fps not in {valid_fps}')

        # hardcoded values
        pulse_dur = 160
        cyc_dur = 33333
        # convert to microseconds 
        interframe_interval = (1/self.fps)*1e6
        # get nframes per cycle
        nframes = np.ceil(cyc_dur / interframe_interval).astype(int)

        if camera =='top':
            bottom_offset = 0
        elif camera == 'bottom':
            bottom_offset = 1750
        else:
            raise ValueError('camera must be one of the following: top, bottom')
        
        times = []
        # get times
        for n in range(nframes):
            t = (interframe_interval * n) + (nazures * pulse_dur) + azure_offset + basler_offset
            t += bottom_offset
            times.append(t)

        # edge case to deal with second frame interfering with azure
        if self.fps in (120, 150):
            times[1] += 510
        # edge case to deal with last frame interfering with azure
        if self.fps == 150 and camera =='bottom':
            times[-1] -= 330

        return times