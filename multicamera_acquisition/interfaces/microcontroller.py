import glob
import logging
import struct
import sys

import matplotlib.pyplot as plt
import numpy as np
import serial
from datetime import datetime, timedelta

STX = b"\x02"
ETX = b"\x03"

AZURE_INTERSUBFRAME_PERIOD = 1575
AZURE_NUM_SUBFRAMES = 9
AZURE_NUM_SUBFRAMES_BEFORE_TRIGGER = 3
AZURE_SUBFRAME_DURATION = 160


def validate_microcontroller_configutation(
    config, n_azures, basler_fps, basler_exposure_time
):
    """
    Validate the microcontroller configuration by ensuring that:
    - No pins are in appropriately repeated.
    - There is at least one top camera trigger pin.
    - If there are Azure cameras, then there is at least one Azure trigger pin.
    - If `n_azures>0` then `basler_fps` must be 30, 60, 90, 120, or 150.
    - If `n_azures>0` and `basler_fps>30` then `basler_exposure_time` must be limited to
      the time between azure subframes.
    - custom output times, pins and states must be the same length, and states must be 0 or 1.
    """
    # check for repeated pins
    all_unique_pins = (
        config["top_camera_pins"]
        + config["top_light_pins"]
        + config["bottom_camera_pins"]
        + config["bottom_light_pins"]
        + config["azure_trigger_pins"]
        + config["random_output_pins"]
        + config["input_pins"]
    )
    if len(all_unique_pins) != len(set(all_unique_pins)):
        raise ValueError(
            "Some pins are repeated within or between the following lists: top_camera_pins, "
            "top_light_pins, bottom_camera_pins, bottom_light_pins, azure_trigger_pins, "
            "random_output_pins, input_pins"
        )
    if len(set(all_unique_pins).intersection(config["custom_output_pins"])) > 0:
        raise ValueError(
            "Some pins are shared between custom_output_pins and other lists of pins."
        )

    # check for at least one top camera trigger pin
    if len(config["top_camera_pins"]) == 0:
        raise ValueError("There must be at least one top camera trigger pin!")

    # check for azure trigger pins
    if n_azures > 0 and len(config["azure_trigger_pins"]) == 0:
        raise ValueError("There must be at least one Azure trigger pin!")

    # check basler fps
    if n_azures > 0 and basler_fps not in [30, 60, 90, 120, 150]:
        raise ValueError(
            "Basler fps must be 30, 60, 90, 120, or 150 when using Azure cameras."
        )

    # check basler exposure time
    if n_azures > 0 and basler_fps > 30:
        max_exposure_time = (
            AZURE_INTERSUBFRAME_PERIOD
            - n_azures * AZURE_SUBFRAME_DURATION
            - 2 * config["gap_between_azure_and_basler"]
        )
        if basler_exposure_time > max_exposure_time:
            raise ValueError(
                f"Basler exposure time must be less than {max_exposure_time} us when using "
                f"{n_azures} Azure cameras and setting `gap_between_azure_and_basler` to "
                f"{config['gap_between_azure_and_basler']} us."
            )

    # check custom output times, pins, and states
    custom_output_lengths = [
        len(config["custom_output_times"]),
        len(config["custom_output_pins"]),
        len(config["custom_output_states"]),
    ]
    if len(set(custom_output_lengths)) > 1:
        raise ValueError(
            "custom_output_times, custom_output_pins, and custom_output_states must be the same length."
        )
    if not np.isin(config["custom_output_states"], [0, 1]).all():
        raise ValueError("custom_output_states must be 0 or 1.")


def plot_trigger_schedule(
    cycle_duration,
    top_basler_trigger_ons,
    top_basler_trigger_offs,
    bottom_basler_trigger_ons,
    bottom_basler_trigger_offs,
    top_basler_light_offs,
    bottom_basler_light_offs,
    azure_state_change_times,
    n_azures,
    figsize,
):
    """
    Plot the schedule of output state changes for the microcontroller.

    Parameters:
    -----------
    cycle_duration : int
        Duration of each acquisition cycle in microseconds.

    top_basler_trigger_ons : list
        List of times at which the top Basler trigger turns on.

    top_basler_trigger_offs : list
        List of times at which the top Basler trigger turns off.

    bottom_basler_trigger_ons : list
        List of times at which the bottom Basler trigger turns on.

    bottom_basler_trigger_offs : list
        List of times at which the bottom Basler trigger turns off.

    top_basler_light_offs : list
        List of times at which the top Basler light turns off.

    bottom_basler_light_offs : list
        List of times at which the bottom Basler light turns off.

    azure_trigger : int
        Pair of times at which the Azure trigger turns on and off.

    n_azures : int
        Number of Azure cameras.

    figsize : tuple
        Figure size.
    """
    fig, ax = plt.subplots(figsize=figsize)

    top_trigger_on = np.zeros(cycle_duration)
    for on, off in zip(top_basler_trigger_ons, top_basler_trigger_offs):
        top_trigger_on[on:off] = 1

    bottom_trigger_on = np.zeros(cycle_duration)
    for on, off in zip(bottom_basler_trigger_ons, bottom_basler_trigger_offs):
        bottom_trigger_on[on:off] = 1

    top_light_on = np.zeros(cycle_duration)
    for on, off in zip(top_basler_trigger_ons, top_basler_light_offs):
        top_light_on[on:off] = 1

    bottom_light_on = np.zeros(cycle_duration)
    for on, off in zip(bottom_basler_trigger_ons, bottom_basler_light_offs):
        bottom_light_on[on:off] = 1

    azure_trigger_on = np.zeros(cycle_duration)
    if n_azures > 0:
        azure_onset = azure_state_change_times[0]
        for i in np.arange(AZURE_NUM_SUBFRAMES) - AZURE_NUM_SUBFRAMES_BEFORE_TRIGGER:
            on = azure_onset + i * AZURE_INTERSUBFRAME_PERIOD
            off = on + AZURE_SUBFRAME_DURATION * n_azures
            azure_trigger_on[on:off] = 1

    for i, signal in enumerate(
        [
            top_trigger_on,
            bottom_trigger_on,
            top_light_on,
            bottom_light_on,
            azure_trigger_on,
        ]
    ):
        ax.fill_between(
            np.arange(cycle_duration),
            signal * 0.8 + i,
            np.ones(cycle_duration) * i,
            color=plt.cm.tab10(i),
            zorder=i + 5,
            linewidth=0,
        )
        ax.fill_between(
            np.arange(cycle_duration),
            signal * 5,
            np.zeros(cycle_duration),
            color=plt.cm.tab10(i),
            zorder=i,
            alpha=0.1,
            linewidth=0,
        )

    labels = [
        "Top Basler trigger",
        "Bottom Basler trigger",
        "Top lights",
        "Bottom lights",
        "Azure acquisition",
    ]
    ax.set_yticks(np.arange(len(labels)) + 0.4)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Time (us)")


def generate_output_schedule(config, n_azures, basler_fps):
    """
    Generate a schedule of output state changes for the microcontroller. The schedule specifies a
    set of state changes on a set of output pins at specific times, which will be performed once
    per acquisition cycle. Acqusition cycles 33333 us long when using 1 or more Azure cameras,
    and otherwise defined by the target frame rate.

    Parameters:
    -----------
    config : dict
        Configuration dictionary. Must contain the following keys:

        - top_camera_pins
            List of pins connected to top cameras. Must be non-empty.
        - top_light_pins:
            List of pins connected to top lights.
        - top_light_dur
            Duration of top light pulses in microseconds.
        - bottom_camera_pins
            List of pins connected to bottom cameras.
        - bottom_light_pins
            List of pins connected to bottom lights.
        - bottom_light_dur
            Duration of bottom light pulses in microseconds.
        - bottom_camera_offset
            Gap between between shutoff of the top lights on onset of the bottom
            camera trigger (ignored if `n_azures>0` and `basler_fps>30`).
        - gap_between_azure_and_basler
            Gap between the end of an Azure acquisition subframe and start of Basler camera acquisition.
        - azure_trigger_pins
            List of pins used to trigger Azure cameras.
        - azure_trigger_dur
            Duration of Azure trigger pulses in microseconds.
        - basler_trigger_dur
            Duration of Basler trigger pulses in microseconds.
        - custom_output_times
            List of times at which to perform additional custom output state changes.
        - custom_output_pins
            List of pins corresponding to the times in `custom_output_times`.
        - custom_output_states
            List of states corresponding to the times in `custom_output_times`.
        - plot_trigger_schedule
            Whether to plot the trigger schedule.
        - trigger_plot_figsize: (10.5, 6)
            Size of figure for visualization of the trigger schedule.

    n_azures : int
        Number of Azure cameras.

    basler_fps : int
        Target rame rate of Basler cameras.

    Returns:
    --------
    state_change_times : list
        List of times at which the microcontroller should change its output state.

    state_change_pins : list
        List of output pins corresponding to the times in `state_change_times`.

    state_change_states : list
        List of output states corresponding to the times in `state_change_times`.

    cycle_duration : int
        Duration of each acquisition cycle in microseconds.
    """
    if n_azures == 0:
        # one cycle per basler frame
        cycle_duration = int(1e6 / basler_fps)

        # azure triggers
        azure_state_change_times = []
        azure_state_change_states = []

        # basler triggers
        top_basler_trigger_ons = [0]
        bottom_delay = config["bottom_camera_offset"] + config["top_light_dur"]

    else:
        # one cycle per azure frame
        cycle_duration = 33333

        # azure triggers
        azure_trig = AZURE_NUM_SUBFRAMES_BEFORE_TRIGGER * AZURE_INTERSUBFRAME_PERIOD
        azure_state_change_times = [azure_trig, azure_trig + config["azure_pulse_dur"]]
        azure_state_change_states = [1, 0]

        # basler triggers
        if basler_fps == 30:
            top_basler_trigger_ons = [AZURE_INTERSUBFRAME_PERIOD * AZURE_NUM_SUBFRAMES]
            bottom_delay = config["bottom_camera_offset"] + config["top_light_dur"]

        else:
            top_basler_first_trigger = (
                AZURE_SUBFRAME_DURATION * n_azures
                + config["gap_between_azure_and_basler"]
            )
            bottom_delay = AZURE_INTERSUBFRAME_PERIOD

            if basler_fps == 60:
                top_basler_trigger_ons = [
                    top_basler_first_trigger,
                    top_basler_first_trigger + int(1e6 / 60),
                ]
            if basler_fps == 90:
                top_basler_trigger_ons = [
                    top_basler_first_trigger,
                    top_basler_first_trigger + AZURE_INTERSUBFRAME_PERIOD * 7,
                    top_basler_first_trigger + int(1e6 / 90 * 2),
                ]
            elif basler_fps == 120:
                top_basler_trigger_ons = [
                    top_basler_first_trigger,
                    top_basler_first_trigger + AZURE_INTERSUBFRAME_PERIOD * 5,
                    top_basler_first_trigger + int(1e6 / 120 * 2),
                    top_basler_first_trigger + int(1e6 / 120 * 3),
                ]
            elif basler_fps == 150:
                top_basler_trigger_ons = [
                    top_basler_first_trigger,
                    top_basler_first_trigger + AZURE_INTERSUBFRAME_PERIOD * 4,
                    top_basler_first_trigger + AZURE_INTERSUBFRAME_PERIOD * 8,
                    top_basler_first_trigger + int(1e6 / 150 * 3),
                    top_basler_first_trigger + int(1e6 / 150 * 4),
                ]

    top_basler_trigger_ons = np.array(top_basler_trigger_ons)
    bottom_basler_trigger_ons = top_basler_trigger_ons + bottom_delay

    top_basler_trigger_offs = top_basler_trigger_ons + config["basler_pulse_dur"]
    bottom_basler_trigger_offs = bottom_basler_trigger_ons + config["basler_pulse_dur"]

    top_basler_light_offs = top_basler_trigger_ons + config["top_light_dur"]
    bottom_basler_light_offs = bottom_basler_trigger_ons + config["bottom_light_dur"]

    state_change_times = [
        np.repeat(top_basler_trigger_ons, len(config["top_camera_pins"])),
        np.repeat(top_basler_trigger_offs, len(config["top_camera_pins"])),
        np.repeat(bottom_basler_trigger_ons, len(config["bottom_camera_pins"])),
        np.repeat(bottom_basler_trigger_offs, len(config["bottom_camera_pins"])),
        np.repeat(top_basler_trigger_ons, len(config["top_light_pins"])),
        np.repeat(top_basler_light_offs, len(config["top_light_pins"])),
        np.repeat(bottom_basler_trigger_ons, len(config["bottom_light_pins"])),
        np.repeat(bottom_basler_light_offs, len(config["bottom_light_pins"])),
        np.repeat(azure_state_change_times, len(config["azure_trigger_pins"])),
        config["custom_output_times"],
    ]

    state_change_pins = [
        np.tile(config["top_camera_pins"], len(top_basler_trigger_ons)),
        np.tile(config["top_camera_pins"], len(top_basler_trigger_offs)),
        np.tile(config["bottom_camera_pins"], len(bottom_basler_trigger_ons)),
        np.tile(config["bottom_camera_pins"], len(bottom_basler_trigger_offs)),
        np.tile(config["top_light_pins"], len(top_basler_trigger_ons)),  # top lights
        np.tile(config["top_light_pins"], len(top_basler_light_offs)),
        np.tile(config["bottom_light_pins"], len(bottom_basler_trigger_ons)),
        np.tile(config["bottom_light_pins"], len(bottom_basler_light_offs)),
        np.tile(config["azure_trigger_pins"], len(azure_state_change_times)),
        config["custom_output_pins"],
    ]

    state_change_states = [
        np.ones(len(top_basler_trigger_ons) * len(config["top_camera_pins"])),
        np.zeros(len(top_basler_trigger_offs) * len(config["top_camera_pins"])),
        np.ones(len(bottom_basler_trigger_ons) * len(config["bottom_camera_pins"])),
        np.zeros(len(bottom_basler_trigger_offs) * len(config["bottom_camera_pins"])),
        np.ones(len(top_basler_trigger_ons) * len(config["top_light_pins"])),
        np.zeros(len(top_basler_light_offs) * len(config["top_light_pins"])),
        np.ones(len(bottom_basler_trigger_ons) * len(config["bottom_light_pins"])),
        np.zeros(len(bottom_basler_light_offs) * len(config["bottom_light_pins"])),
        np.repeat(azure_state_change_states, len(config["azure_trigger_pins"])),
        config["custom_output_states"],
    ]

    state_change_times = np.concatenate(state_change_times).astype(int)
    state_change_pins = np.concatenate(state_change_pins).astype(int)
    state_change_states = np.concatenate(state_change_states).astype(int)

    # sort by time
    sort_inds = np.argsort(state_change_times)
    state_change_times = state_change_times[sort_inds]
    state_change_pins = state_change_pins[sort_inds]
    state_change_states = state_change_states[sort_inds]

    # confirm that times are within one cycle
    if np.any(state_change_times >= cycle_duration):
        raise ValueError(
            "Some state change times are greater than the acquisition cycle duration!"
        )

    # plot trigger schedule if desired
    if config["plot_trigger_schedule"]:
        plot_trigger_schedule(
            cycle_duration,
            top_basler_trigger_ons,
            top_basler_trigger_offs,
            bottom_basler_trigger_ons,
            bottom_basler_trigger_offs,
            top_basler_light_offs,
            bottom_basler_light_offs,
            azure_state_change_times,
            n_azures,
            config["trigger_plot_figsize"],
        )

    return state_change_times, state_change_pins, state_change_states, cycle_duration


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


class Microcontroller(object):
    """
    Handles communication with microcontroller for triggering cameras/lights and performing sync IO.

    Attributes:
    - config (dict): Configuration dictionary.
    - serial_connection (serial.Serial): Serial connection to microcontroller.
    - state_change_times: Times at which the microcontroller should change its output state each cycle.
    - state_change_pins: Output pins corresponding to the times in `state_change_times`.
    - state_change_states: States corresponding to the times in `state_change_times`.
    - cycle_duration: Duration of each acquisition cycle in microseconds.
    """

    def __init__(
        self,
        basename=None,
        config=None,
        basler_fps=120,
        n_azures=2,
        basler_exposure_time=950,
    ):
        """
        Save attributes, creates a triggerdata file, determines the schedule of output state changes
        that the microcontroller should perform during each acquisition cycle, and validates the config.

        Parameters:
        -----------
        basename : str, optional
            Basename of the acquisition. If None then no triggerdata file is created.

        config : dict, optional
            Configuration dictionary for the whole acquisition, which should contain a
            microcontroller-specific config under the key "microcontroller". If None
            then a default config is used.

        basler_fps : int, optional
            Target frame rate of Basler cameras. Used if `config` is None.

        n_azures : int, optional
            Number of Azure cameras. Used if `config` is None.

        basler_exposure_time : int, optional
            Exposure time of Basler cameras in microseconds. Used if `config` is None.
        """

        # Try to find the main logger
        try:
            self.logger = logging.getLogger("main_acq_logger")
        except:
            self.logger = logging.getLogger("microcontroller_logger")

        # extract relevant config parameters
        if config is not None:
            self.config = config["microcontroller"]
            basler_fps = config["globals"]["fps"]
            n_azures = len(
                [c for c in config["cameras"].values() if c["brand"] == "azure"]
            )
            exposure_times = [
                c["exposure"]
                for c in config["cameras"].values()
                if c["brand"] in ["basler", "flir"]
            ]
            basler_exposure_time = max(exposure_times)
        else:
            # TODO: this needs to guess at an fps? might not really work..
            self.config = self.default_microcontroller_config()

        # set light durations if not specified
        if self.config["top_light_dur"] is None:
            self.config["top_light_dur"] = basler_exposure_time
        if self.config["bottom_light_dur"] is None:
            self.config["bottom_light_dur"] = basler_exposure_time

        # validate config
        validate_microcontroller_configutation(
            self.config, n_azures, basler_fps, basler_exposure_time
        )

        # determine schedule of output state changes
        (
            self.state_change_times,
            self.state_change_pins,
            self.state_change_states,
            self.cycle_duration,
        ) = generate_output_schedule(self.config, n_azures, basler_fps)

        # initialize empty serial connection
        self.serial_connection = None

        # create triggerdata file
        if basename is None:
            self.trigger_data_file = None
        else:
            header = "time,pin,state\n"
            self.trigger_data_file = open(f"{basename}.triggerdata.csv", "w")
            self.trigger_data_file.write(header)
            self.logger.debug(f"Created triggerdata file: {basename}.triggerdata.csv")

    def check_for_response(self, serial_connection, expected_response, port=""):
        """Check if the microcontroller sends an expected response within 5 seconds."""
        for _ in range(50):  # connection has 0.1 second timeout
            msg = serial_connection.readline().decode("utf-8").strip("\n")
            self.logger.debug(
                f"`check_for_response` on port {port}. Recieved: {msg} from microcontroller. Expected: {expected_response}"
            )
            if msg == expected_response:
                return True
        return False

    def open_serial_connection(self, port=None):
        """
        Open serial connection with the microcontroller. Use the port specified in the config file if
        it exists, otherwise find the port automatically. After the connection is established, check for
        a READY message from the microcontroller. If the message is not received, raise a RuntimeError.

        Parameters:
        -----------
        port : str, optional
            Serial port to use. Overrides the port specified in the config file.
        """
        if port is None:
            port = self.config["microcontroller_port"]

        if port is None:
            ports = find_serial_ports()
            if len(ports) == 0:
                raise RuntimeError(
                    "No serial ports available! (Close all open serial connections!)"
                )

            for port in ports:
                with serial.Serial(port=port, timeout=0.1) as serial_connection:
                    found_ready_microcontroller = self.check_for_response(
                        serial_connection, "READY", port
                    )
                    if found_ready_microcontroller:
                        break
        else:
            with serial.Serial(port=port, timeout=0.1) as serial_connection:
                found_ready_microcontroller = self.check_for_response(
                    serial_connection, "READY", port
                )

        if found_ready_microcontroller:
            self.serial_connection = serial.Serial(port=port, timeout=0.1)
            self.logger.info(f"Found ready microcontroller on port: {port}")
        else:
            raise RuntimeError(
                "Could not find ready microcontroller! Try restarting the microcontroller."
            )

    def close(self):
        """
        Close the serial connection and the triggerdata file.
        """
        self.serial_connection.close()
        if self.trigger_data_file is not None:
            self.trigger_data_file.close()

    def start_acquisition(self, recording_duration_s):
        """
        Start acquisition by sending instructions to the microcontroller. Raise a RuntimeError if the
        microcontroller does not respond with the string "RECEIVED" within 2 seconds.
        """

        # calculate number of acquisition cycles
        num_cycles = int(recording_duration_s * 1e6 / self.cycle_duration)

        lines_to_send = (
            STX,
            str(num_cycles).encode(),
            str(self.cycle_duration).encode(),
            ",".join(map(str, self.config["input_pins"])).encode(),
            ",".join(map(str, self.config["random_output_pins"])).encode(),
            str(self.config["cycles_per_random_bit_flip"]).encode(),
            ",".join(map(str, self.state_change_times)).encode(),
            ",".join(map(str, self.state_change_pins)).encode(),
            ",".join(map(str, self.state_change_states)).encode(),
            ETX,
        )

        # wrtie sequence to microcontroller
        for line in lines_to_send:
            self.serial_connection.write(line + b"\n")

        # flush input buffer to get rid of READY messages
        self.serial_connection.reset_input_buffer()

        # check for response
        acquisition_started = self.check_for_response(
            self.serial_connection, "RECEIVED"
        )

        if not acquisition_started:
            raise RuntimeError(
                "Could not start acquisition! microcontroller did not respond with RECEIVED."
            )

    def interrupt_acquisition(self):
        """
        Interrupt acquisition. Raise a RuntimeError if the microcontroller does not respond
        with the string "INTERRUPTED" within 2 seconds.
        """
        self.serial_connection.reset_input_buffer()
        self.serial_connection.write(b"I")

        # check for correct response
        acquisition_interrupted = self.check_for_response(
            self.serial_connection, "INTERRUPTED"
        )
        if not acquisition_interrupted:
            raise RuntimeError(
                "Could not interrupt acquisition! microcontroller did not recieve interrupt signal."
            )
        else:
            self.logger.info("Microcontroller acquisition loop interrupted.")

    def check_for_input(self):
        """
        Check for input from the microcontroller. Two kinds of input are possible:
        - The character "F\n" indicates that the microcontroller has finished the acquisition loop.
        - A triggerdata message reporting the state of the microcontroller's input pins that
          has the format "<STX><pin><state><micros><cycleIndex>\n"

        Returns:
        --------
        finished : bool
            True if the microcontroller has finished the acquisition loop, False otherwise.
        """
        if self.serial_connection.in_waiting > 0:
            char = self.serial_connection.read(1)
            if char == b"F":
                self.serial_connection.read(1)  # read newline
                return True
            elif char == STX:
                data = self.serial_connection.read(12)
                if self.trigger_data_file is not None:
                    pin, state, micros, cycleIndex = struct.unpack("<HBLL", data[:-1])
                    time = cycleIndex * self.cycle_duration + micros
                    self.trigger_data_file.write(f"{time},{pin},{state}\n")
            else:
                raise RuntimeError(f"Unexpected character from microcontroller: {char}")
        return False

    @staticmethod
    def default_microcontroller_config():
        return {
            "azure_trigger_pins": [0],
            "top_camera_pins": [1, 3, 5, 7, 9],
            "bottom_camera_pins": [11],
            "input_pins": [10],
            "top_light_pins": [38, 39, 40, 41, 14, 15],
            "bottom_light_pins": [16, 17, 20, 21, 22, 23],
            "top_light_dur": None,
            "bottom_light_dur": None,
            "random_output_pins": [],
            "custom_output_pins": [],
            "custom_output_times": [],
            "custom_output_states": [],
            "azure_pulse_dur": 100,
            "basler_pulse_dur": 100,
            "bottom_camera_offset": 100,
            "gap_between_azure_and_basler": 50,
            "trigger_plot_figsize": (12, 3),
            "plot_trigger_schedule": True,
            "microcontroller_port": None,
            "cycles_per_random_bit_flip": 1,
        }


def run_microcontroller_standalone(config, recording_duration_s):
    """
    Run the microcontroller in standalone mode. This emulates the microcontroller's behavior
    during acquisition, but without any camera communication or logging of triggerdata.

    Parameters:
    -----------
    config : dict, optional
        Configuration dictionary for the whole acquisition, which should contain a
        microcontroller-specific config under the key "microcontroller". If None
        then a default config is used.

    recording_duration_s : int
        Duration of the recording in seconds. Recording can also be stopped using a
        keyboard interrupt (ctrl+c).
    """
    microcontroller = Microcontroller(config=config)
    microcontroller.open_serial_connection()
    microcontroller.start_acquisition(recording_duration_s)

    datetime_prev = datetime.now()
    datetime_rec_start = datetime_prev
    endtime = datetime_prev + timedelta(seconds=recording_duration_s)

    try:
        while not microcontroller.check_for_input():
            if (datetime.now() - datetime_prev).total_seconds() > 1:
                total_sec = (datetime.now() - datetime_rec_start).seconds
                pct_prog = np.round(total_sec / recording_duration_s * 100, 2)

                print(
                    f"\rRecording Progress: {pct_prog}% ({total_sec} / {recording_duration_s} sec)",
                    end="",
                )
                datetime_prev = datetime.now()
    except KeyboardInterrupt:
        microcontroller.interrupt_acquisition()
    finally:
        microcontroller.close()
