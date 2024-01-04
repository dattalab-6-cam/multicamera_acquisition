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

def generate_basler_frametimes(config, n_azures=2, camera_type='top'):
    """Generate trigger times for Basler camera frames accounting for Azure camera synchronization.

    Parameters
    ----------
    config : dict
        Configuration dictionary containing parameters to generate azure pulses.
            Config dict MUST contain
                fps : int
                    Frames per second
                bottom_offset: int
                    Amount to shift basler frame grabs for bottom cameras
                basler_offset: int
                    Amount to offset basler from Azure
                azure_offset: int
                    Amount to offset Azures from eachother
                acq_cycle_dur : int 
                    Duration of acq cycle (shouldn't really change beyond 33,333)
                azure_pulse_dur: int
                    Duration of azure ir pulse
    n_azures : int, optional
        Number of Azure cameras (default is 2).
    camera_type : str, optional
        Determines the bottom offset for camera synchronization. Set in the main acquisition loop when iterating cameras.

    Returns
    -------
    list
        A list of timestamps representing Basler camera frame times adjusted for Azure synchronization.
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
    """Generate Azure pulse times and handle offsets for triggering.

    Parameters
    ----------
    config : dict
        Configuration dictionary containing parameters to generate azure pulses.
            Config dict MUST contain
                azure_pulse_dur : int
                    Duration of illumination of azure
                azure_idle_time: int
                    Duration of period between end of one ir pulse and start of another
                trigger_offset : bool
                    Whether to offset azure times based on arduino trigger
                acq_cycle_dur : int 
                    Duration of acq cycle (shouldn't really change beyond 33,333)

    n_azures : int, optional
        Number of Azure cameras (default is 2).

    Returns
    -------
    list
        A list of tuples representing start and end times of Azure camera pulses.
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

def viz_triggers(config, camera_type='top', n_pulses=2, n_azures=2):
    """Visualize the synchronization triggers for Azure and Basler cameras.

    Parameters
    ----------
    config : dict
        Configuration dictionary containing parameters to generate azure pulses.
            Config dict MUST contain
                trigger_viz_figsize : tuple[int, int]
                    Size of figure for visualization
                acq_cycle_dur : int 
                    Duration of acq cycle (shouldn't really change beyond 33,333)
    camera_type : str, optional
        Type of the camera to visualize triggers for; either 'top' or 'bottom' (default is 'top').
    n_azures : int, optional
        Number of Azure cameras (default is 2).

    Returns
    -------
    tuple
        A tuple containing the generated figure and axes objects.
    """

    azure_times = generate_azure_pulse_inds(n_azures=n_azures)
    basler_times = generate_basler_frametimes(camera_type=camera_type, n_azures=2)

    # plotting
    fig = plt.figure(figsize=config['trigger_viz_figsize'])
    ax = plt.gca()
    ax.set_ylim(0, 2)
    ax.set_xlim((0, config['acq_cycle_dur']))

    for n in range(n_pulses):
        x0, x1 = azure_times[n]
        ax.axvline(x0, ymax=1/2)
        ax.axvline(x1, ymax=1/2)
        ax.axhline(1.0, xmin=(x0/config['acq_cycle_dur']), xmax=x1/config['acq_cycle_dur'])

    for t in basler_times:
        plt.axvline(t, ymax=1/2, color='red')
    plt.show()

    return fig, ax

class Arduino(object):

    def __init__(self):
        pass
    
    @staticmethod
    def default_arduino_config():
        pass