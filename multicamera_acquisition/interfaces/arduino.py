import struct
import numpy as np
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


def validate_arduino_config(config):
    """
    Validate the configuration dictionary for the Arduino interface. Checks that
    - no pins are reused for different purposes
    - XXX
    """
    # JACK TODO: write this function


def generate_output_schedule(config):
    """
    Generate a sequence of state changes for the output pins of the arduino.
    These changes will be performed during each acquisition cycle and will be used
    to trigger cameras and lights.

    Parameters:
    ----------
    config : dict
        Configuration dictionary.

    Returns:
    --------
    times : list
        The time in microseconds at which each state change should occur.
    pins : list
        The output pin for each state change.
    states : list
        The state (0 or 1) for each state change.
    """
    # JACK TODO: write this function, make sure to raise errors if the timing cant work out
    pass


def check_for_response(serial_connection, expected_response):
    """
    Check if the arduino sends an expected response within 2 seconds.
    """
    for i in range(20):  # connection has 0.1 second timeout
        msg = serial_connection.readline().decode("utf-8").strip("\r\n")
        if msg == expected_response:
            return True
    return False


def read_until_byte(serial_connection, byte, limit=1000):
    """
    Read from the serial connection until the specified byte is received.

    Parameters:
    -----------
    serial_connection : serial.Serial
        The serial connection to read from.

    byte : bytes
        The byte to read until.

    limit : int
        The maximum number of bytes to read before giving up.
    """
    msg = b""
    for i in range(limit):
        msg += serial_connection.read()
        if msg[-1] == byte:
            break
    return msg


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
    Handles communication with arduino for triggering cameras and lights, and performing sync IO.

    Attributes:
    - config (dict): Configuration dictionary.
    - serial_connection (serial.Serial): Serial connection to arduino.
    - output_schedule: Sequence of state changes per acquisition cycle as a tuple (times, pins, states).
    """

    def __init__(self, basename, config):
        """
        Save attributes, creates a triggerdata file, determines the schedule of output state changes
        that the arduino should perform during each acquisition cycle, and validates the config.
        """
        # save attributes
        self.config = config
        self.serial_connection = None

        # create triggerdata file
        input_pins = self.config["trigger_data_input_pins"]
        if len(input_pins) > 0:
            header = "time," + ",".join([f"pin_{pin}" for pin in input_pins]) + "\n"
            self.trigger_data_file = open(f"{basename}.triggerdata.csv", "w")
            self.trigger_data_file.write(header)

        # validate the schedule and config
        validate_arduino_config(config, self.output_schedule)

        # determine schedule of output state changes
        self.output_schedule = generate_output_schedule(config)

        # vizualize the schedule if requested
        if config["arduino"]["plot_trigger_schedule"]:
            self.viz_triggers()

    def open_serial_connection(self):
        """
        Open serial connection with the arduino. Use the port specified in the config file if
        it exists, otherwise find the port automatically. After the connection is established, check for
        a READY message from the arduino. If the message is not received, raise a RuntimeError.
        """
        if self.config["arduino"]["port"] is None:
            ports = find_serial_ports()
            if len(ports) == 0:
                raise RuntimeError("No serial ports found!")

            for port in ports:
                with serial.Serial(port=port, timeout=0.1) as serial_connection:
                    found_ready_arduino = check_for_response(serial_connection, "READY")
                    if found_ready_arduino:
                        break
        else:
            port = self.config["arduino"]["port"]
            with serial.Serial(port=port, timeout=0.1) as serial_connection:
                found_ready_arduino = check_for_response(serial_connection, "READY")

        if found_ready_arduino:
            self.serial_connection = serial.Serial(port=port, timeout=0.1)
            print(f"Fount ready arduino on port: {port}")
        else:
            raise RuntimeError(
                "Could not find ready arduino! Try restarting the arduino."
            )

    def close(self):
        """
        Close the serial connection and the triggerdata file.
        """
        self.serial_connection.close()
        self.trigger_data_file.close()

    def start_acquisition(self):
        """
        Start acquisition by sending instructions to the arduino. Raise a RuntimeError if the
        arduino does not respond with the string "RECEIVED" within 2 seconds.
        """
        # flush input buffer to get rid of READY messages
        self.serial_connection.flushInput()

        # send instructions to arduino
        # JACK TODO: send instructions to arduino

        # check for response
        acquisition_started = check_for_response(self.serial_connection, "RECEIVED")
        if not acquisition_started:
            raise RuntimeError(
                "Could not start acquisition! Arduino did not respond with RECEIVED."
            )

    def interrupt_acquisition(self):
        """
        Interrupt acquisition. Raise a RuntimeError if the arduino does not respond
        with the string "INTERRUPTED" within 2 seconds.
        """
        # JACK TODO: write interrupt message to arduino, check for response
        pass

    def check_for_input(self):
        """
        Check for input from the arduino. Two kinds of input are possible:
        - The character "F<ETX>" indicates that the arduino has finished the acquisition loop.
        - A triggerdata message, which reports the state of the arduino's input pins and
          has the format "<STX><pin1><state1>...<pinN><stateN><cycleIndex><ETX>"

        Returns:
        --------
        finished : bool
            True if the arduino has finished the acquisition loop, False otherwise.
        """
        if self.serial_connection.in_waiting > 0:
            msg = read_until_byte(self.serial_connection, b"\x03")
            if msg == b"F\x03":
                return True
            elif msg[0] == "\x02":
                # JACK TODO: parse triggerdata message, write to file
                pass
            else:
                raise RuntimeError(f"Unexpected message from arduino: {msg}")
        return False

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
        assert self.fps in valid_fps, ValueError(f"fps not in {valid_fps}")

        # convert to microseconds
        interframe_interval = (1 / self.fps) * 1e6
        # get nframes per cycle
        nframes = np.ceil(self.acq_cycle_dur / interframe_interval).astype(int)

        if self.camera_type == "top":
            bottom_offset = 0
        elif self.camera_type == "bottom":
            bottom_offset = 1750
        else:
            raise ValueError("camera must be one of the following: top, bottom")

        times = []
        # get times
        for n in range(nframes):
            t = (
                (interframe_interval * n)
                + (self.nazures * self.azure_pulse_dur)
                + self.azure_offset
                + self.basler_offset
            )
            t += bottom_offset
            times.append(t)

        # edge case to deal with second frame interfering with azure
        if self.fps in (120, 150):
            times[1] += 510
        # edge case to deal with last frame interfering with azure
        if self.fps == 150 and self.camera_type == "bottom":
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
            x0 = (self.pulse_dur * self.nazures + self.idle_time) * (n + 1)

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

    def viz_triggers(self):
        """
        Visualize the synchronization triggers for Azure and Basler cameras.

        Returns:
        - tuple: A tuple containing the generated figure and axes objects.

        Used attributes:
        - self.generate_azure_pulse_inds(): Generates Azure pulse times for visualization.
        - self.generate_basler_frametimes(): Generates Basler frame times for visualization.
        - self.trigger_viz_figsize: Size of the figure for visualization.
        - self.acq_cycle_dur: Duration of the acquisition cycle.
        - self.n_pulses: Number of pulses.
        """

        azure_times = self.generate_azure_pulse_inds()
        basler_times = self.generate_basler_frametimes()

        # plotting
        fig = plt.figure(figsize=self.trigger_viz_figsize)
        ax = plt.gca()
        ax.set_ylim(0, 2)
        ax.set_xlim((0, self.acq_cycle_dur))

        for n in range(self.n_pulses):
            x0, x1 = azure_times[n]
            ax.axvline(x0, ymax=1 / 2)
            ax.axvline(x1, ymax=1 / 2)
            ax.axhline(
                1.0, xmin=(x0 / self.acq_cycle_dur), xmax=x1 / self.acq_cycle_dur
            )

        for t in basler_times:
            plt.axvline(t, ymax=1 / 2, color="red")

        plt.show()

        return fig, ax
