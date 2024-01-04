import struct
import numpy as np
import yaml
import warnings
import sys
import glob
import serial
import logging
import matplotlib.pyplot as plt


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
    - bottom_offset(int): Offset for bottom cameras (i.e. add const. to top camera times to shift to left.)
    - basler_offset (int): Offset duration for Basler camera pulse.
    - azure_offset (int): Offset duration for Azure camera pulse.
    - n_azures (int): Number of Azure cameras

    """

    def __init__(self, config_file, config, n_azures=2):
        
        # self.config_file = config_file
        # self.config = config
        
        # # n_azures will be determined in the main acq lopp
        # n_azures = n_azures
        # # never changes
        # self.n_pulses = 9
        pass
    
    @staticmethod
    def default_arduino_config(fps):

        # """
        # Generates a default configuration for Arduino setup with given frames per second (FPS).

        # Args:
        # - fps (int): Frames per second for the system.

        # Returns:
        # - dict: Default configuration dictionary with preset parameters for synchronization.
        # """

        # config = {
        #     'fps': fps,
        #     'azure_pulse_dur': 160,
        #     'acq_cycle_dur': 33333,
        #     'basler_offset': 10,
        #     'azure_offset': 10,
        #     'bottom_offset': 1750,
        #     'azure_idle_time': 1450,
        #     'trigger_offset': True
        # }

        # return config
        pass


def generate_basler_frametimes(config, n_azures=2, camera_type='top'):
    """
    Generate trigger times for Basler camera frames accounting for Azure camera synchronization.
    Args:
    - camera_type: Determines the bottom offset for camera synchronization. Set in main acq loop when iterating cameras
    Used attributes:
    - config['fps']: Used to calculate interframe_interval.
    - config['acq_cycle_dur']: Used to determine the number of frames per cycle.
    - config['basler_offset']: Used in time calculation for Basler frames.
    Returns:
    - list: A list of timestamps representing Basler camera frame times adjusted for Azure synchronization.
    Raises:
    - ValueError: If the provided FPS is not within the valid supported frame rates [30, 60, 90, 120, 150].
    - ValueError: If the camera parameter is not 'top' or 'bottom'.
    """

    valid_fps = [30, 60, 90, 120, 150]
    assert config['fps'] in valid_fps, ValueError(f'fps not in {valid_fps}')
    # convert to microseconds
    interframe_interval = (1/config['fps'])*1e6
    # get nframes per cycle
    nframes = np.ceil(config['acq_cycle_dur'] / interframe_interval).astype(int)
    if camera_type =='top':
        _offset = 0
    elif camera_type == 'bottom':
        _offset = config['bottom_offset']
    else:
        raise ValueError('camera must be one of the following: top, bottom')
    times = []
    # get times
    for n in range(nframes):
        t = (interframe_interval * n) + (n_azures * config['azure_pulse_dur']) + config['azure_offset'] + config['basler_offset']
        t += _offset
        times.append(t)
    # edge case to deal with second frame interfering with azure
    if config['fps'] in (120, 150):
        times[1] += 510
    # edge case to deal with last frame interfering with azure
    if config['fps'] == 150 and camera_type =='bottom':
        times[-1] -= 330
    return times

def generate_azure_pulse_inds(config, n_azures=2):
    """
    Generate Azure pulse times and handle offsets for triggering.
    Used attributes:
    - n_azures: Used to calculate the number of pulses.
    - config['azure_pulse_dur']: Duration of each pulse.
    - config['acq_cycle_dur']: Used in determining pulse times.
    - config['trigger_offset']: Determines if an offset for triggering is applied.
    - config['azure_idle_time']: Idle time between pulses.
    Returns:
    - list: A list of tuples representing start and end times of Azure camera pulses.
    Notes:
    - This method modifies the 'azure_pulse_times' attribute.
    """
    # never changes
    n_pulses = 9
    # generate azure pulse times
    azure_pulse_times = []
    x0 = 0
    for n in range(n_pulses):
        x1 = x0 + (n_azures * config['azure_pulse_dur'])
        azure_pulse_times.append((x0, x1))
        x0=(config['azure_pulse_dur'] * n_azures + config['azure_idle_time'])*(n+1)
    if config['trigger_offset']:
        # get offsets to deal with cases 
        post_offset = azure_pulse_times[3][0]
        pre_offset = config['acq_cycle_dur'] - post_offset
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
        for n in range(pre_trigger, n_pulses):
            x0, x1 = azure_pulse_times[n]
            x0 -= post_offset
            x1 -= post_offset
            azure_pulse_times[n] = (x0, x1)
    return azure_pulse_times

def viz_triggers(self, camera_type='top'):
    """
    Visualize the synchronization triggers for Azure and Basler cameras.
    Returns:
    - tuple: A tuple containing the generated figure and axes objects.
    Used attributes:
    - self.generate_azure_pulse_inds(): Generates Azure pulse times for visualization.
    - self.generate_basler_frametimes(): Generates Basler frame times for visualization.
    - self.config['trigger_viz_figsize']: Size of the figure for visualization.
    - self.config['acq_cycle_dur']: Duration of the acquisition cycle.
    - self.n_pulses: Number of pulses.
    """
    azure_times = self.generate_azure_pulse_inds()
    basler_times = self.generate_basler_frametimes(camera_type=camera_type)
    # plotting
    fig = plt.figure(figsize=self.config['trigger_viz_figsize'])
    ax = plt.gca()
    ax.set_ylim(0, 2)
    ax.set_xlim((0, self.config['acq_cycle_dur']))
    for n in range(self.n_pulses):
        x0, x1 = azure_times[n]
        ax.axvline(x0, ymax=1/2)
        ax.axvline(x1, ymax=1/2)
        ax.axhline(1.0, xmin=(x0/self.config['acq_cycle_dur']), xmax=x1/self.config['acq_cycle_dur'])
    for t in basler_times:
        plt.axvline(t, ymax=1/2, color='red')
    plt.show()
    return fig, ax