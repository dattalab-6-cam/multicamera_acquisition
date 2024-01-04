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

    """
    Represents an Arduino setup for synchronization between cameras.

    Attributes:
    - config (dict): Configuration dictionary containing parameters like FPS, pulse durations, cycle durations,
                     camera type, and offsets for synchronization.
    - fps (int): Frames per second of the system.
    - azure_pulse_dur (int): Duration of the ir pulse for the Azure camera.
    - acq_cycle_dur (int): Duration of the acquisition cycle.
    - camera_type (str): Type of the camera to trigger; either 'top' or 'bottom'.
    - basler_offset (int): Offset duration for Basler camera pulse.
    - azure_offset (int): Offset duration for Azure camera pulse.
    - n_azures (int): Number of Azure cameras

    """


    def __init__(self, config):
        
        self.config = config
        
        self.fps = self.config['fps']
        self.azure_pulse_dur = self.config['azure_pulse_dur']
        self.acq_cycle_dur = self.config['acq_cycle_dur']
        self.camera_type = self.config['camera_type_arduino']
        self.basler_offset = self.config['basler_offset']
        self.azure_offset = self.config['azure_offset']
        self.n_azures = self.config['n_azures']

        self.n_pulses = self.config['n_pulses']
        self.azure_idle_time = self.config['azure_idle_time']
        self.trigger_offset = self.config['trigger_offset']

        return None
    def generate_basler_frametimes(self):
        """
        Generate trigger times for Basler camera frames accounting for Azure camera synchronization.

        Used attributes:
        - self.fps: Used to calculate interframe_interval.
        - self.acq_cycle_dur: Used to determine the number of frames per cycle.
        - self.camera_type: Determines the bottom offset for camera synchronization.
        - self.basler_offset: Used in time calculation for Basler frames.

        Returns:
        - list: A list of timestamps representing Basler camera frame times adjusted for Azure synchronization.

        Raises:
        - ValueError: If the provided FPS is not within the valid supported frame rates [30, 60, 90, 120, 150].
        - ValueError: If the camera parameter is not 'top' or 'bottom'.
        """
        valid_fps = [30, 60, 90, 120, 150]
        assert self.fps in valid_fps, ValueError(f'fps not in {valid_fps}')

        # convert to microseconds
        interframe_interval = (1/self.fps)*1e6
        # get nframes per cycle
        nframes = np.ceil(self.acq_cycle_dur / interframe_interval).astype(int)

        if self.camera_type =='top':
            bottom_offset = 0
        elif self.camera_type == 'bottom':
            bottom_offset = 1750
        else:
            raise ValueError('camera must be one of the following: top, bottom')

        times = []
        # get times
        for n in range(nframes):
            t = (interframe_interval * n) + (self.nazures * self.azure_pulse_dur) + self.azure_offset + self.basler_offset
            t += bottom_offset
            times.append(t)

        # edge case to deal with second frame interfering with azure
        if self.fps in (120, 150):
            times[1] += 510
        # edge case to deal with last frame interfering with azure
        if self.fps == 150 and self.camera_type =='bottom':
            times[-1] -= 330

        return times
    
    def generate_azure_pulse_inds(self):

        """
        Generate Azure pulse times and handle offsets for triggering.

        Used attributes:
        - self.n_azures: Used to calculate the number of pulses.
        - self.azure_pulse_dur: Duration of each pulse.
        - self.acq_cycle_dur: Used in determining pulse times.
        - self.trigger_offset: Determines if an offset for triggering is applied.
        - self.azure_idle_time: Idle time between pulses.

        Returns:
        - list: A list of tuples representing start and end times of Azure camera pulses.

        Notes:
        - This method modifies the 'azure_pulse_times' attribute.

        """

        # generate azure pulse times
        azure_pulse_times = []
        x0 = 0
        for n in range(self.n_pulses):
            x1 = x0 + (self.nazures * self.pulse_dur)
            azure_pulse_times.append((x0, x1))
            x0=(self.pulse_dur * self.nazures + self.idle_time)*(n+1)

        if self.trigger_offset:
            # get offsets to deal with cases 
            post_offset = azure_pulse_times[3][0]
            pre_offset = self.acq_cycle_dur - post_offset
            # number of pulses precreding arduino trigger
            pre_trigger = 3
            # add offset to move first three pulses to end
            for n in range(pre_trigger):
                x0, x1 = azure_pulse_times[n]
                x0 += pre_offset
                x1 += pre_offset
                azure_pulse_times[n] = (x0, x1)
            # offset pulses post trigger
            # now subtract to move last 6 pulses start at t = 0
            for n in range(pre_trigger, self.n_pulses):
                x0, x1 = azure_pulse_times[n]
                x0 -= post_offset
                x1 -= post_offset
                azure_pulse_times[n] = (x0, x1)

        return azure_pulse_times
