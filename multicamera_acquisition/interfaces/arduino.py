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


def validate_arduino_config(config):
    """
    Validate the configuration dictionary for the Arduino interface. Checks that
    - no pins are reused for different purposes
    - XXX
    """
    # get all pins into one list
    pins = (
        config["arduino"]["input_pins"]
        + config["arduino"]["random_pins"]
        + config["arduino"]["output_pins"]
    )
    # check if lengths match after removing duplicates with set()
    assert len(pins) == len(
        set(pins)
    ), "Pins should only be specified once, please remove duplicate pins in config"


def generate_output_schedule(config, n_azures=2):
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
    toptimes = generate_basler_frametimes(config, n_azures=n_azures, camera_type="top")
    bottomtimes = generate_basler_frametimes(
        config, n_azures=n_azures, camera_type="bottom"
    )

    # expand toptimes to have a time for each pin
    def _expand_arr(x, y):
        return [_x for _x in x for _ in range(y)]

    n_top_pins = len(config["arduino"]["top_camera_pins"]) + len(
        config["arduino"]["top_light_pins"]
    )
    toptimes_expanded = _expand_arr(toptimes, n_top_pins)

    n_bottom_pins = len(config["arduino"]["bottom_camera_pins"]) + len(
        config["arduino"]["bottom_light_pins"]
    )
    bottomtimes_expanded = _expand_arr(bottomtimes, n_bottom_pins)

    # expand pins to correpond to times
    top_pins = config["arduino"]["top_camera_pins"] * len(toptimes) + config["arduino"][
        "top_light_pins"
    ] * len(toptimes)
    bottom_pins = config["arduino"]["bottom_camera_pins"] * len(bottomtimes) + config[
        "arduino"
    ]["bottom_light_pins"] * len(bottomtimes)

    def _generate_states(times):
        return [1 if i % 2 == 0 else 0 for i in range(len(times))]

    # generate and expand states to appropriate pins pins
    topstates = _generate_states(toptimes)
    topstates_expanded = _expand_arr(topstates, n_top_pins)

    bottomstates = _generate_states(bottomtimes)
    bottomstates_expanded = _expand_arr(bottomstates, n_bottom_pins)

    # concat all into final lists to return
    times = toptimes_expanded + bottomtimes_expanded
    pins = top_pins + bottom_pins
    states = topstates_expanded + bottomstates_expanded

    # add azure times/pins
    for pin, azure_time in zip(
        config["arduino"]["azure_pins"], config["arduino"]["azure_times"]
    ):
        pins.append(pin)
        times.append(azure_time)
        states.append(1)

    return times, pins, states


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


def generate_basler_frametimes(config, n_azures=2, camera_type="top"):
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
    assert config["fps"] in valid_fps, ValueError(f"fps not in {valid_fps}")

    # convert to microseconds
    interframe_interval = (1 / config["fps"]) * 1e6

    # get nframes per cycle
    nframes = np.ceil(config["acq_cycle_dur"] / interframe_interval).astype(int)
    if camera_type == "top":
        _offset = 0
    elif camera_type == "bottom":
        _offset = config["bottom_offset"]
    else:
        raise ValueError("camera must be one of the following: top, bottom")
    times = []

    # get times
    for n in range(nframes):
        t = (
            (interframe_interval * n)
            + (n_azures * config["azure_pulse_dur"])
            + config["azure_offset"]
            + config["basler_offset"]
        )
        t += _offset
        end = t + config["exposure_time"]
        times.append(int(t))
        times.append(int(end))

    # edge case to deal with second frame interfering with azure
    if config["fps"] in (120, 150):
        times[1] += 510

    # edge case to deal with last frame interfering with azure
    if config["fps"] == 150 and camera_type == "bottom":
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
        x1 = x0 + (n_azures * config["azure_pulse_dur"])
        azure_pulse_times.append((x0, x1))
        x0 = (config["azure_pulse_dur"] * n_azures + config["azure_idle_time"]) * (
            n + 1
        )

    if config["trigger_offset"]:
        # get offsets to deal with cases
        post_offset = azure_pulse_times[3][0]
        pre_offset = config["acq_cycle_dur"] - post_offset
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


def viz_triggers(config, camera_type="top", n_pulses=2, n_azures=2):
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
    fig = plt.figure(figsize=config["trigger_viz_figsize"])
    ax = plt.gca()
    ax.set_ylim(0, 2)
    ax.set_xlim((0, config["acq_cycle_dur"]))

    for n in range(n_pulses):
        x0, x1 = azure_times[n]
        ax.axvline(x0, ymax=1 / 2)
        ax.axvline(x1, ymax=1 / 2)
        ax.axhline(
            1.0, xmin=(x0 / config["acq_cycle_dur"]), xmax=x1 / config["acq_cycle_dur"]
        )

    for t in basler_times:
        plt.axvline(t, ymax=1 / 2, color="red")
    plt.show()

    return fig, ax


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

    def start_acquisition(self, num_cycles, azure_fps=30):
        """
        Start acquisition by sending instructions to the arduino. Raise a RuntimeError if the
        arduino does not respond with the string "RECEIVED" within 2 seconds.
        """
        # flush input buffer to get rid of READY messages
        self.serial_connection.flushInput()

        # send instructions to arduino
        # JACK TODO: send instructions to arduino\

        # acq duration based off azure framerate of 30 hz
        cycle_dur = int((1 / azure_fps) * 1e6)
        # n cycles between each input pin state check
        input_check_interval = self.config["arduino"]["input_check_interval"]
        # n cycles between each random bit update
        random_flip_interval = self.config["arduino"]["random_flip_interval"]
        # get output pin times, pin numbers, and states
        times, outpins, states = generate_output_schedule(self.config)

        sequence = (
            b"\x02" + f"{num_cycles}\n".encode(),
            f"{cycle_dur}\n".encode(),
            (",".join(map(str, self.config["arduino"]["input_pins"])) + "\n").encode(),
            f",{input_check_interval},".encode()
            + (
                ",".join(map(str, self.config["arduino"]["random_pins"])) + "\n"
            ).encode(),
            f",{random_flip_interval},".encode() + ",".join(map(str, times)).encode(),
            (",".join(map(str, outpins)) + "\n").encode(),
            ",".join(map(str, states)).encode() + b"\x03",
        )
        for seq in sequence:
            self.serial_connection.write(seq)

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
        # flush
        self.serial_connection.flushInput()
        # send interrupt signal
        self.serial_connection.write(b"I")
        # check for correct response
        acquisition_interrupted = check_for_response(
            self.serial_connection, "INTERRUPTED"
        )
        if not acquisition_interrupted:
            raise RuntimeError(
                "Could not interrupt acquisition! Arduino did not recieve interrupt signal."
            )

    def check_for_input(self):
        """
        Check for input from the arduino. Two kinds of input are possible:
        - The character "F<\n>" indicates that the arduino has finished the acquisition loop.
        - A triggerdata message, which reports the state of the arduino's input pins and
          has the format "<STX><pin1><state1>...<pinN><stateN><cycleIndex><ETX>"

        Returns:
        --------
        finished : bool
            True if the arduino has finished the acquisition loop, False otherwise.
        """
        if self.serial_connection.in_waiting > 0:
            # msg = read_until_byte(self.serial_connection, b"\x03")
            msg = self.serial_connection.readline()
            if msg == b"F\x03":
                # parse bytes
                # elif msg[0] == "\x02":
                #     # JACK TODO: parse triggerdata message, write to file

                pass
            else:
                raise RuntimeError(f"Unexpected message from arduino: {msg}")
        return False
