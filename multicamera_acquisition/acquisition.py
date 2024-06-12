import logging
import multiprocessing as mp
import os
import cv2
import traceback
from datetime import datetime, timedelta
from glob import glob
from logging import StreamHandler
from logging.handlers import QueueListener
from os.path import exists, join
from pathlib import Path

import numpy as np

from multicamera_acquisition.config import (
    load_config,
    save_config,
    validate_recording_config,
)
from multicamera_acquisition.interfaces.camera_azure import enumerate_azure_cameras
from multicamera_acquisition.interfaces.camera_base import CameraError, get_camera
from multicamera_acquisition.interfaces.camera_basler import enumerate_basler_cameras
from multicamera_acquisition.interfaces.microcontroller import Microcontroller
from multicamera_acquisition.logging_utils import setup_child_logger
from multicamera_acquisition.visualization import MultiDisplay
from multicamera_acquisition.writer import get_writer


class AcquisitionLoop(mp.Process):
    """A process that acquires images from a camera
    and writes them to a queue.
    """

    def __init__(
        self,
        write_queue,
        display_queue,
        camera_device_index,
        camera_config,
        write_queue_depth=None,
        acq_loop_config=None,
        logger_queue=None,
        logging_level=logging.DEBUG,
        process_name=None,
        fps=None,
    ):
        """
        Parameters
        ----------
        write_queue : multiprocessing.Queue
            A queue to which frames will be written.

        display_queue : multiprocessing.Queue
            A queue from which frames will be read for display.

        camera_device_index : int
            The device index of the camera to acquire from.

        camera_config : dict
            A config dict for the Camera.

        write_queue_depth : multiprocessing.Queue (default: None)
            A queue to which depth frames will be written (azure only).

        acq_loop_config : dict (default: None)
            A config dict for the AcquisitionLoop.
            If None, the default config will be used.

        logger_queue : multiprocessing.Queue (default: None)
            A queue to which the logger will write messages.
            If None, the root logger will be used.

        logging_level : int (default: logging.DEBUG)
            The logging level to use for the logger.

        process_name : str (default: None)
            The name of the process.

        fps : int (default: None)
            The fps of the acquisition, as controlled by either the camera or the microcontroller.
            Only used to determine the timeout for the camera.get_array() call.
            If None, the timeout will be set to 1000 ms.

        """

        # Save the process name for logging purposes
        super().__init__(name=process_name)

        # Save values
        self.write_queue = write_queue
        self.display_queue = display_queue
        self.write_queue_depth = write_queue_depth
        self.camera_config = camera_config
        self.camera_device_index = camera_device_index
        self.logger_queue = logger_queue
        self.logging_level = logging_level
        self.fps = fps

        # Get config
        if acq_loop_config is None:
            self.acq_config = self.default_acq_loop_config().copy()
        else:
            self.acq_config = acq_loop_config

        # Check for Nones in camera config
        if self.camera_config is None:
            raise ValueError("Camera config cannot be None")

        # Set up events for mp coordination
        self._create_mp_events()

    @staticmethod
    def default_acq_loop_config():
        """Get the default config for the acquisition loop."""
        return {
            "display_every_n": 1,
            "downsample": 4,
            "dropped_frame_warnings": False,
            "max_frames_to_acqure": None,
        }

    def _create_mp_events(self):
        """Create multiprocessing events for coordination with the main acquisition function."""
        self.await_process = (
            mp.Event()
        )  # the main thread calls .wait() on this and waits for it to be .set() from the acq loop process
        self.await_main_thread = (
            mp.Event()
        )  # the acq loop process calls .wait() and waits for it to be .set() from the main thread via the _continue_from_main_thread() method.
        self.stopped = (
            mp.Event()
        )  #  the main thread can interrupt acquisition by setting this event via the .stop() method.

    def _continue_from_main_thread(self):
        """Tell the acquisition loop to continue (called from the main thread)."""
        self.await_main_thread.set()
        self.await_process.clear()  # reset this event so we can use it again

    def stop(self):
        """Set this  AcquisitionLoop's stopped event. This will stop the acquisition loop.

        This must be done via an mp.Event — it cannot be done by setting a flag directly in the main func,
        (for example by setting self.stopped = True), because the mp.Event is shared across processes,
        whereas the flag would not be shared across processes and the acquisition loop would not see it change.
        """
        self.stopped.set()

    def run(self):
        """Launch a separate subprocess to acquire frames."""

        # Set the process group ID to to the process ID so it isn't affected by the main process's stop signal
        os.setpgid(0, 0)

        # Set up logging. In the typical case, we set up a logger to communicate
        # with the main process via a Queue.
        if self.logger_queue is None:
            # Just use the root logger
            self.logger = logging.getLogger()
        elif isinstance(self.logger_queue, mp.queues.Queue):
            # Create a logger for this process
            # (it will automatically include the process name in the log output)
            logger = setup_child_logger(self.logger_queue, level=self.logging_level)
            self.logger = logger
        else:
            raise ValueError("logger_queue must be a multiprocessing.Queue or None.")
        self.logger.debug(f"Started acq loop for {self.camera_config['name']}")

        """
        CAMERA INFO

        Basler camera objects cannot be pickled, so we have to initialize the cameras
        here, in each of their respective subprocesses. When we call get_camera, 
        the returned "cam" object contains all the config info ready to go, but 
        it won't actually contain a camera object until cam.init() is called. This will
        call .Open() on the camera object itself, and update all the camera's parameters. The pyplon
        camera itself is available from here as cam.cam (i.e. you could call directly cam.cam.Open()).

        Once the camera is ready, this code will wait for the main function to confirm that
        *all* the cameras are ready, and then it will tell the camera to start acquiring frames
        (cam.start()).

        The reason for all this abstraction is that it allows us to write separate camera classes
        for different brands of camera (Basler, Azure, FLIR...) but have one AcquisitionLoop code
        that is agnostic to the brand of camera being used.
        """
        # Get the Camera object instance
        try:
            # TODO: this is a fairly thin wrapper around the class init, and maybe
            # we could just call the class init directly here for clarity.
            cam = get_camera(
                brand=self.camera_config["brand"],
                id=self.camera_device_index,
                name=self.camera_config["name"],
                config=self.camera_config,
            )
        except Exception as e:
            # show the entire traceback
            self.logger.error(traceback.format_exc())
            raise e

        # Actually open / initialize the connection to the camera
        self.logger.debug(f"About to initialize camera {self.camera_config['name']}")
        cam.init()

        # Report that the process has initialized the camera
        self.await_process.set()  # report to the main loop that the camera is ready

        # Here, the main thread will loop through all the acq loop objects
        # and start each camera. The main thread will wait for
        # each acq loop to report that it has started its camera.

        # Wait for the main thread to get to the for-loop
        # where it will then wait for the camera to start
        self.logger.debug("Waiting for main thread")
        self.await_main_thread.wait()

        # Once we get the go-ahead, tell the camera to start grabbing
        cam.start()

        # Once the camera is started grabbing, allow the main
        # thread to continue
        self.await_process.set()  # report to the main loop that the camera is ready

        """
        FRAME ACQUISITION INFO
        Here, we acquire frames from the camera! Hurray, this is the fun part!

        During acquisition, we loop over calls of cam.get_array() to get the image.

        cam.get_array() returns the following information for Basler cameras:
            -- img: the image data
            -- linestatus: the line status of the image (if get_linestatus=True, else None)
            -- camera_timestamp: the device camera_timestamp of the image (if get_timestamp=True, else None)

        cam.get_array() returns the following information for Azure cameras:
            -- depth: the depth data
            -- ir: the ir data
            -- color: the color data (if get_color=True, else None)
            -- camera_timestamp: the device camera_timestamp of the image (if get_timestamp=True, else None)


        We then send the images out for writing to disk and keep track of the following
        information:
            -- n_frames_received: how many total frames have been successfully received
              from the camera). This value is compared with max_frames_to_acqure to see if 
              it's time to stop the acquisition. Otherwise, the acquisition loop will continue forever
              until the .stopped event is set from the main loop. Note that if the cameras are
              running in triggered mode (i.e. from a Teensy), then this doesn't necessarily mean 
              that they will acquire infinite frames, as they need a trigger to acquire a frame.

            -- current_iter: the current iteration of the loop. With no dropped frames, this should match 1:1
              with n_frames_received.

            -- prev_timestamp: the device camera_timestamp of the most recently acquire frame. This is used
              to compare to the current frame camera_timestamp to determine if a frame has been dropped.
              Currently, the threshold for dropping a frame is a difference larger than 1.25x the expected
              inter-frame period. There is no strong reason for this value, it just works decently.

        Once a frame is received, we unpack the data. If the camera is an azure, then the data consists of 
        (depth, ir, camera_timestamp). If the camera is a basler, then the data consists of (image, camera_timestamp) (assuming
        that get_timestamp was True in the call to get_array, which it is always here). Then we write the data
        to the Writer queue. If the camera is an azure, we also write the depth data to the depth writer queue.
        """
        # Get ready to record
        current_iter = 0
        n_frames_received = 0
        first_frame = False  # We will give the first frame a long time out, to allow the serial comm. to connect
        timeout = 1000 if self.fps is None else int(1000 / self.fps * 1.25)
        prev_timestamp = 0

        # Acquire frames until we receive the stop signal
        self.logger.debug("Ready to record")
        while not self.stopped.is_set():
            try:
                if first_frame:
                    _cam_data = cam.get_array(
                        timeout=1000 * 60, get_timestamp=True
                    )  # increase timeout of first frame
                    first_frame = False
                    self.logger.debug("First frame received")
                    prev_timestamp = _cam_data[
                        -1
                    ]  # camera_timestamp is always the final element of the _cam_data tuple
                else:
                    _cam_data = cam.get_array(timeout=timeout, get_timestamp=True)

                # If we received a frame:
                # TODO: this enqueueing code can be rewritten / simplified a bit.
                if _cam_data[0].size > 0:

                    # Increment the frame counter (distinct from number of while loop iterations)
                    n_frames_received += 1

                    # If this is an azure camera, we write the depth data to a separate queue
                    if self.camera_config["brand"] == "azure":
                        depth, ir, _, camera_timestamp = _cam_data

                        # writer expects (img, line_status, camera_timestamp, self.frames_received),
                        # but Azure has no concept of line_status, so we just pass None.
                        self.write_queue.put(
                            tuple([ir, None, camera_timestamp, n_frames_received])
                        )
                        self.write_queue_depth.put(
                            tuple([depth, None, camera_timestamp, n_frames_received])
                        )
                        if self.camera_config["display"]["display_frames"]:
                            if n_frames_received % self.display_every_n == 0:
                                self.display_queue.put(
                                    depth[
                                        :: self.acq_config["downsample"],
                                        :: self.acq_config["downsample"],
                                    ],
                                )
                    else:
                        img, linestatus, camera_timestamp = _cam_data
                        self.write_queue.put(
                            (img, linestatus, camera_timestamp, n_frames_received)
                        )  # writer exepcts (img, line_status, camera_timestamp, self.frames_received)
                        if self.camera_config["display"]["display_frames"]:
                            if (
                                n_frames_received % self.acq_config["display_every_n"]
                                == 0
                            ):
                                if self.camera_config["pixel_format"] == "BayerRG8":
                                    img = cv2.cvtColor(img, cv2.COLOR_BAYER_RG2BGR)
                                self.display_queue.put(
                                    img[
                                        :: self.acq_config["downsample"],
                                        :: self.acq_config["downsample"],
                                    ]
                                )

                    # Check if we dropped any frames
                    delta_t = (camera_timestamp - prev_timestamp) / 1e6
                    if (
                        self.acq_config["dropped_frame_warnings"]
                        and delta_t > (timeout) * 1.25
                    ):
                        self.logger.warning(
                            f"Dropped frame on iter {current_iter} after receiving {n_frames_received} frames (delta_t={delta_t} ms, threshold={timeout*1.25} ms)"
                        )
                    prev_timestamp = camera_timestamp

            # Catch any frame timeouts
            except Exception as e:

                if type(e).__name__ == "SpinnakerException":
                    pass
                elif (
                    type(e).__name__ == "TimeoutException"
                    or type(e).__name__ == "K4ATimeoutException"
                ):
                    if self.acq_config["dropped_frame_warnings"]:
                        self.logger.warning(
                            f"Frame grabbing timed out, not nec. a dropped frame ( on iter {current_iter} after receiving {n_frames_received} frames)"
                        )
                    pass
                else:
                    self.logger.error(traceback.format_exc())
                    raise e

            # Increment the iteration counter
            current_iter += 1

            # Check if we've reached the max frames to acquire
            if self.acq_config["max_frames_to_acqure"] is not None:
                if n_frames_received >= self.acq_config["max_frames_to_acqure"]:
                    if not self.stopped.is_set():
                        self.logger.debug(
                            f"Reached max frames to acquire ({self.acq_config['max_frames_to_acqure']}), stopping."
                        )
                        self.stopped.set()
                    break

        # Once the stop signal is received, stop the writer and dispaly processes
        self.logger.debug(
            f"Received {n_frames_received} frames over {current_iter} iterations, {self.camera_config['name']}"
        )

        # We use empty tuples to signal the writer that no more frames are coming, and it can safely close the video.
        self.logger.debug(
            f"Writing empties to stop queue, {self.camera_config['name']}"
        )
        self.write_queue.put(tuple())
        if self.write_queue_depth is not None:
            self.write_queue_depth.put(tuple())
        if self.display_queue is not None:
            self.display_queue.put(tuple())

        """ 
        CAMERA CLOSING INFO
        Here we close the camera. This actually consists of a few actions.
            1) tell the camera to stop grabbing frames
            2) close the camera's connection to the computer
            3) delete the .cam attribute (ie the camera object) from our custom Camera class.
              This means that you could restart acquisition from the same camera by calling 
              cam.init() + cam.start() again.
        """

        self.logger.debug(f"Closing camera {self.camera_config['name']}")
        cam.close()
        self.logger.debug("Camera closed")

        # Report that the process has stopped
        self.logger.debug(f"Acq loop for {self.camera_config['name']} is finished.")


# Never used?
# def generate_full_config(camera_lists):
#     full_config = {}
#     acquisition_config = AcquisitionLoop.default_acq_loop_config().copy()
#     microcontroller_config = Microcontroller.default_microcontroller_config().copy()
#     full_camera_config = create_full_camera_default_config(camera_lists)
#     full_config["acq_loop"] = acquisition_config
#     full_config["microcontroller"] = microcontroller_config
#     full_config["cameras"] = full_camera_config

#     # write to file
#     with open("full_config.yaml", "w") as f:
#         yaml.dump(full_config, f)
#     return full_config


def end_processes(acquisition_loops, writers, disp, writer_timeout=60):
    """Use the stop() method to end the acquisition loops, writers, and display
    processes, escalating to terminate() if necessary.
    """
    # Get the main logger
    logger = logging.getLogger("main_acq_logger")

    # End acquisition loop processes
    for acquisition_loop in acquisition_loops:
        if acquisition_loop.is_alive():
            logger.debug(
                f"stopping acquisition loop ({acquisition_loop.camera_config['name']})",
            )

            # Send a stop signal to the process
            acquisition_loop.stop()

            # Wait for the process to finish
            logger.debug(
                f"joining acquisition loop ({acquisition_loop.camera_config['name']})",
            )
            acquisition_loop.join(timeout=1)
            # acquisition_loop.join(timeout=60 * 60)

            # If still alive, terminate it
            if acquisition_loop.is_alive():
                # debug: notify user we had to terminate the acq loop
                logger.warning(
                    f"Terminating acquisition loop {acquisition_loop.camera_config['name']} (join timed out)"
                )
                acquisition_loop.terminate()

    # End writer processes
    for writer in writers:
        if writer.is_alive():
            writer.join(timeout=writer_timeout)
        logger.debug(f"Writer exitcode: {writer.exitcode}")

    # End display processes
    if disp is not None:
        # TODO figure out why display.join hangs when there is >1 azure
        if disp.is_alive():
            disp.join(timeout=1)
        if disp.is_alive():
            disp.terminate()


def resolve_device_indices(config):
    """Resolve device indices for all cameras in the config.

    Parameters
    ----------
    config : dict
        The recording config.

    Returns
    -------
    device_index_dict : dict
        A dict mapping camera names to device indices.
    """

    device_index_dict = {}

    # Resolve any Basler cameras
    serial_nos, _ = enumerate_basler_cameras(behav_on_none="pass")
    for camera_name, camera_dict in config["cameras"].items():
        if camera_dict["brand"] not in ["basler", "basler_emulated"]:
            continue
        if camera_dict["id"] is None:
            raise ValueError(f"Camera {camera_name} has no id specified.")
        elif isinstance(camera_dict["id"], int):
            dev_idx = camera_dict["id"]
        elif isinstance(camera_dict["id"], str):
            if camera_dict["id"] not in serial_nos:
                raise CameraError(
                    f"Camera with serial number {camera_dict['id']} not found."
                )
            else:
                dev_idx = serial_nos.index(camera_dict["id"])
        device_index_dict[camera_name] = dev_idx

    # Resolve any Azure cameras
    if any(
        [camera_dict["brand"] == "azure" for camera_dict in config["cameras"].values()]
    ):
        serial_nos_dict = enumerate_azure_cameras()
        serial_nos_dict = {v: k for k, v in serial_nos_dict.items()}
        for camera_name, camera_dict in config["cameras"].items():
            if camera_dict["brand"] not in ["azure"]:
                continue
            if camera_dict["id"] is None:
                raise ValueError(f"Camera {camera_name} has no id specified.")
            elif isinstance(camera_dict["id"], int):
                dev_idx = camera_dict["id"]
            elif isinstance(camera_dict["id"], str):
                if camera_dict["id"] not in list(serial_nos_dict.keys()):
                    raise CameraError(
                        f"Camera with serial number {camera_dict['id']} not found."
                    )
                else:
                    dev_idx = serial_nos_dict[camera_dict["id"]]
            device_index_dict[camera_name] = dev_idx

    # Resolve any Lucid cameras
    # TODO

    return device_index_dict


def refactor_acquire_video(
    save_location,
    config,
    recording_duration_s=60,
    recording_name=None,
    append_datetime=True,
    append_camera_serial=False,
    overwrite=False,
    logging_level=logging.INFO,
):
    """Acquire video from multiple, synchronized cameras.

    This is the "main" function that controls the acquisition of the videos.

    The basic flow for this function is as follows:

    1. Set up the recording. This involves creating the save location, loading the
        recording config, communicating with the Arduino to set the intended
        frame rate + lighting schedule, and setting up the main logger.
    2. Prepare to launch separate sub-processes to acquire frames from each camera,
        to write the frames to disk, and optionally, to display the frames in real-time.
    3. Start the sub-processes (see lines 803 - 809, where writer.start() and acquisition_loop.start() are called).
    4. Wait for the specified duration
    5. End the sub-processes and close the microcontroller serial connection.

    Parameters
    ----------
    save_location : str or Path
        The directory in which to save the recording.

    config : dict or str or Path
        A dict containing the recording config, or a filepath to a yaml file
        containing the recording config.

    recording_duration_s : int (default: 60)
        The duration of the recording in seconds.

    recording_name : str (default: None)
        The name of the recording. If None, the recording will be named with
        the current date and time.
            The final save location will be:
                /path/to/my/[recording_name]/[recording_name].[camera_name].mp4
            OR if append_camera_serial is True:
                /path/to/my/[recording_name]/[recording_name].[camera_name].[camera_serial].mp4
            OR if append_datetime is True:
                /path/to/my/[recording_name]_[datetime]/[recording_name]_[datetime].[camera_name].mp4
            OR if max_video_frames is set in the writer config, then the
            final save location will be:
                /path/to/my/[recording_name]/[recording_name].[camera_name].0.mp4
                /path/to/my/[recording_name]/[recording_name].[camera_name].[max].mp4
                /path/to/my/[recording_name]/[recording_name].[camera_name].[2*max].mp4
                ...


    append_datetime : bool (default: True)
        Whether to further nest the recording in a subfolder named with the
        date and time.

    append_camera_serial : bool (default: True)
        Whether to append the camera serial number to the file name.

    overwrite : bool (default: False)
        Whether to overwrite the save location if it already exists.

    logging_level : int (default: logging.INFO)
        The logging level to use for the logger.

    Returns
    -------
    save_location : Path
        The directory in which the recording was saved.

    config: dict
        The final recording config used.

    Examples
    --------
    A full config file follows the following rough layout:

        globals:
            [list of global params]
        cameras:
            camera_1:
                [list of attributes per camera]
                [list of trigger-specific attributes]
                [list of writer-specific attributes]
            camera_2:
                ...
        acq_loop:
            [list of acquisition loop params]
        rt_display:
            [list of rt display params]
        microcontroller:
            [list of microcontroller params]

    For example, here is a minimal config file for a single camera without an microcontroller:

        globals:
            fps: 30
            microcontroller_required: False  # since trigger short name is set to no_trigger
        cameras:
            top:
                name: top
                brand: basler
                id: "12345678"  # ie the serial number, as a string
                gain: 6
                gamma: 1.0
                exposure: 1000
                display:
                    display_frames: True
                    display_range: (0, 255)
                roi: null  # or an roi to crop the image
                trigger:
                    trigger_type: no_trigger  # convenience attr for no-trigger acquisition
                writer:
                    codec: h264
                    fmt: YUV420
                    gpu: null
                    max_video_frames: 2592000
                    multipass: '0'
                    pixel_format: gray8
                    preset: P1
                    profile: high
                    tuning_info: ultra_low_latency
        acq_loop:
            display_every_n: 4
            dropped_frame_warnings: False
            max_frames_to_acqure: null
        rt_display:
            downsample: 4
            range: [0, 1000]
    """
    current_mp_start_method = mp.get_start_method()
    if current_mp_start_method != "spawn":
        mp.set_start_method("spawn", force=True)

    """
    LOGGING INFO
    Recall that we use subprocesses to acquire and write frames. There is no way to
    directly share a logger across processes. Instead, we use a QueueListener to
    send log messages from the subprocesses to the main process, where they are
    handled by a StreamHandler. This is set up in the main process, and the QueueListener
    is started before the subprocesses are created. The subprocesses are then created
    with a logger_queue argument, which is a Queue that they use to send log messages.

    References:
    https://superfastpython.com/multiprocessing-logging-in-python/
    https://docs.python.org/3/howto/logging-cookbook.html
    """
    # Set up the main logger for this process
    logger = logging.getLogger("main_acq_logger")
    logger.setLevel(logging_level)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.debug("Set up main logger.")
    logger.info("Starting recording...")

    # TODO: could set up a second logger for microcontroller messages

    # Set up the mp logger to log across processes
    logger_queue = mp.Queue()
    queue_listener = QueueListener(logger_queue, StreamHandler())
    queue_listener.start()
    logger.debug("Started mp logging.")

    """
    RECORDING NAME / PATH INFO
    We have agreed on the following basic structure for the name of the recordings:
        recording_name = [recording base name].[camera info].[video info]

    Where:
        recording base name: the name of the recording, eg "test_recording". 
            This MUST NOT contain any dots.
            This may or may not include the date and time, depending on the append_datetime flag.
            Valid examples: "20240101_my_mouse", "test_recording", "test_recording_21-03-01-12-00-00-000000"

        camera info: the name of the camera, eg "top", "bottom", "side". This may also include the serial number of the camera.
            Valid examples: "top", "bottom", "side3", "top.12345678", "azure_top", "azure_top_depth"

        video info: the type of video, and, if max_video_frames is set in the config, the first frame number of the video.
            Valid examples: ".mp4", "0.mp4" [i.e. the first video from this Writer], "1000.mp4" [i.e. a video starting with the 1000th frame from this Writer]
        
    """
    # Create the recording directory
    datetime_str = datetime.now().strftime("%y-%m-%d-%H-%M-%S-%f")
    if recording_name is None:
        assert append_datetime, "Must append datetime if recording_name is None"
        recording_name = datetime_str
    elif append_datetime:
        recording_name = f"{recording_name}_{datetime_str}"
    full_save_location = Path(
        join(save_location, recording_name)
    )  # /path/to/my/recording_name

    if (
        exists(full_save_location)
        and len(glob(join(full_save_location, "*.mp4"))) > 0
        and not overwrite
    ):
        raise ValueError(
            f"Save location {full_save_location} already exists with at least one MP4. If you want save into this dir anyways and risk overwriting, set overwrite to True!"
        )
    os.makedirs(full_save_location, exist_ok=True)
    basename = str(
        full_save_location / recording_name
    )  # /path/to/my/recording_name/recording_name, which will have strings appended to become, eg, /path/to/my/recording_name/recording_name.top.mp4

    logger.debug(f"Have good save location {full_save_location}")

    """
    CONFIG INFO
    We have agreed on the following principles for using config files to structure our recordings:
        
        1. At run-time, WYSIWYG [what you see is what you get] — the config that you pass to refactor_acquire_video IS EXACTLY the config that gets run. 
            No defaults will be auto-populated. You must pass a config, and a copy will get saved into the recording directory.
            The config file can be specified as a dict, or as a path (string or Path) to a yaml file.
            The code will automatically distribute the config parameters to the appropriate classes (Camera, Writer, MultiDisplay, etc.) 
        
        2. However, when **testing** the code, it is desireable to not provide configs every time.
            So, each class (Camera, Writer, MultiDisplay, etc.) has a default config as a static method. The test suite relies extensively on this default config.
            Additionally, these defaults are instructive to users who are looking to understand what parameters each class takes, 
            although the defaults are not always exhaustive.

    """

    # Load the config file if it exists
    if isinstance(config, str) or isinstance(config, Path):
        config = load_config(config)
    else:
        assert isinstance(config, dict)

    # Check that the config is valid
    validate_recording_config(config, logging_level)

    # Save the config file before starting the recording
    config_filepath = Path(basename + ".recording_config.yaml")
    save_config(config_filepath, config)

    """
    CAMERA INFO
    
    The Basler cameras that we use are easily human-identifiable by their serial numbers, e.g. "12345678".
    However, the software that we use to control the cameras (Pylon) uses device indices, e.g. 0, 1, 2, etc.
    The mapping from serial number to device index can change if cameras are added or removed, so it is safest to 
    provide serial numbers, and then resolve the device indices at runtime. This is done by the resolve_device_indices function.
    
    During testing, it is desireable to not have to provide serial numbers every time. Therefore, it is possible
    to simply provide device indices as camera id's in the config (i.e. use camera 0, camera 1, etc.).

    NB: in the config, there is only one spot for a camera "id" — this can be either an integer (device index) or a string (serial number).
    """
    # Resolve camera device indices
    device_index_dict = resolve_device_indices(config)

    """
    ARDUINO INFO
    
    TODO: CW write block comment about the arduino
        -- explain triggerdata file, otherwise that file is "silent" from the perspective of the main function
    """

    # Find the microcontroller to be used for triggering
    if config["globals"]["microcontroller_required"]:
        logger.info("Finding microcontroller...")
        microcontroller = Microcontroller(basename, config)
        microcontroller.open_serial_connection()

    """
    SUBPROCESS INFO
    
    In order to acquire frames from multiple cameras at once, we use subprocesses. Each camera has its own AcquisitionLoop and Writer processes.
    This is necessary in order to record at the highest speeds possible, since Python can't otherwise 
    do multi-threading.

    In this module, each subprocess is subclassed from mp.Process, and has a run() method that is called when the .start() method is called on the class.
    The code in the run() method lives in its own subprocess. Importantly, all of the subprocesses are "spawned" not "forked",
    which means that they are completely independent of the main process, and do not share memory with the main process (this 
    is critical for how the Basler API works on the backend; see https://github.com/basler/pypylon/issues/659#issuecomment-1970761941.)

    """
    # Create the various processes
    # TODO: refactor these into one "running processes" dict or sth like that
    logger.info("Opening subprocesses and cameras, this may take a moment...")
    writers = []
    acquisition_loops = []
    display_queues = []
    camera_list = []
    display_ranges = []

    try:
        for camera_name, camera_dict in config["cameras"].items():
            # Create a writer queue
            write_queue = (
                mp.Queue()
            )  # This queue is used to send frames from the AcuqisitionLoop process to the Writer process

            # Generate file names
            if append_camera_serial:
                cam_append_str = f".{camera_dict['name']}.{camera_dict['id']}.mp4"  # TODO: using camera_dict["id"] here will not always append the serial, since ID can alternatively be an integer
            else:
                cam_append_str = f".{camera_dict['name']}.mp4"
            video_file_name = Path(basename + cam_append_str)
            metadata_file_name = Path(
                basename + cam_append_str.replace(".mp4", ".metadata.csv")
            )

            # Get a writer process
            # TODO: this is a pretty thin wrapper around the class init's, and maybe
            # we could just call the class init's directly here for clarity.
            if camera_dict["brand"] == "basler":
                camera_pixel_format = camera_dict["pixel_format"]
            else:
                camera_pixel_format = "Mono8"

            writer = get_writer(
                write_queue,
                video_file_name,
                metadata_file_name,
                camera_pixel_format=camera_pixel_format,
                writer_type=camera_dict["writer"]["type"],
                config=camera_dict["writer"],
                process_name=f"{camera_name}_writer",
                logger_queue=logger_queue,
                logging_level=logging_level,
            )

            # Get a second writer process for depth if needed
            if camera_dict["brand"] == "azure":
                write_queue_depth = mp.Queue()
                if append_camera_serial:
                    cam_append_str = (
                        f".{camera_dict['name']}_depth.{camera_dict['id']}.avi"
                    )
                else:
                    cam_append_str = f".{camera_dict['name']}_depth.avi"
                video_file_name_depth = Path(basename + cam_append_str)
                metadata_file_name_depth = Path(
                    basename + cam_append_str.replace(".avi", ".metadata.csv")
                )
                writer_depth = get_writer(
                    write_queue_depth,
                    video_file_name_depth,
                    metadata_file_name_depth,
                    camera_pixel_format="Mono16",
                    writer_type=camera_dict["writer"]["type"],
                    config=camera_dict["writer_depth"],
                    process_name=f"{camera_name}_writer_depth",
                    logger_queue=logger_queue,
                    logging_level=logging_level,
                )
            else:
                write_queue_depth = None

            # Setup display queue for camera if requested
            if camera_dict["display"]["display_frames"] is True:
                display_queue = (
                    mp.Queue()
                )  # This queue is used to send frames from the AcuqisitionLoop process to the MultiDisplay process
                display_queues.append(display_queue)
                camera_list.append(camera_name)
                display_ranges.append(camera_dict["display"]["display_range"])
            else:
                display_queue = None

            # Create an acquisition loop process
            acquisition_loop = AcquisitionLoop(
                write_queue=write_queue,
                display_queue=display_queue,
                camera_device_index=device_index_dict[camera_name],
                camera_config=camera_dict,
                write_queue_depth=write_queue_depth,
                acq_loop_config=config["acq_loop"],
                logger_queue=logger_queue,
                logging_level=logging_level,
                process_name=f"{camera_name}_acqLoop",
                fps=config["globals"]["fps"],
            )

            # Start the writer and acquisition loop processes
            writer.start()
            writers.append(writer)
            if camera_dict["brand"] == "azure":
                writer_depth.start()
                writers.append(writer_depth)
            acquisition_loop.start()
            acquisition_loops.append(acquisition_loop)

            # Block until the acq loop process reports that it's initialized
            logger.debug(
                f"Waiting for acquisition loop ({camera_name}) to initialize..."
            )
            status = acquisition_loop.await_process.wait(3)
            if not status:
                raise CameraError(
                    f"Acq loop for {acquisition_loop.camera_config['name']} failed to initialize."
                )
    except Exception as e:
        end_processes(acquisition_loops, [], None)
        microcontroller.close()
        raise e

    if len(display_queues) > 0:
        # create a display process which recieves frames from the acquisition loops
        display_proc = MultiDisplay(
            display_queues,
            camera_list=camera_list,
            display_ranges=display_ranges,
            config=config["rt_display"],
            logger_queue=logger_queue,
            logging_level=logging_level,
        )
        display_proc.start()
    else:
        display_proc = None

    """
    AWAITING INFO
    At this point, the acquisition loops and writers are running, and the display process is running if needed.
    However, no frames have been acquired because the acqisition loops are waiting for the main thread to tell them to continue,
    and also for the arduino to start sending triggers (assuming you're acquiring in trigger mode).
    
    Here, the main thread tells them to go ahead and start their cameras. Usually this is only a few 100 ms per camera,
    so we wait up to 3 seconds per camera, and after that, if any camera fails to start, we raise an error.

    Then once the cameras have been successfully started, we tell the microcontroller to start sending triggers.
    """
    # Wait for the acq loop processes to start their cameras
    logger.info("Starting cameras...")
    for acquisition_loop in acquisition_loops:
        acquisition_loop._continue_from_main_thread()
        status = acquisition_loop.await_process.wait(timeout=3)
        if not status:
            raise CameraError(
                f"Camera {acquisition_loop.camera_config['name']} failed to initialize."
            )

    # Tell microcontroller to start the acquisition loop
    if config["globals"]["microcontroller_required"]:
        logger.info("Starting microcontroller...")
        microcontroller.start_acquisition(recording_duration_s)

    """
    RECORDING MONITORING INFO
    Now we wait for the specified duration for the recording to finish. The microcontroller 
    checks for any incoming triggers, and records them, for post-hoc synchronization of other data streams.

    This is all done in a try/except/finally block because even if an error comes up, we want to end all the sub-proceses
    gracefully and close the microcontroller connection.

    Sometimes (eg during testing) it is useful to put a limit on the total number of frames that are acquired
    by the acquisition loops; if the acquisition loops reach this limit, then acquisition_loop.is_alive() will return False,
    and we can break out of the loop early.
    """
    # Wait for the specified duration
    try:
        print("\rRecording Progress: 0%", end="")

        datetime_prev = datetime.now()
        datetime_rec_start = datetime_prev
        endtime = datetime_prev + timedelta(seconds=recording_duration_s + 10)

        while datetime.now() < endtime:
            if config["globals"]["microcontroller_required"]:
                # Tell the microcontroller to check for input trigger data or finish signal
                finished = microcontroller.check_for_input()
                if finished:
                    logger.debug("Finished recieved from microcontroller")
                    break
            elif not any(
                [acquisition_loop.is_alive() for acquisition_loop in acquisition_loops]
            ):
                # If no microcontroller, then there might be a frame limit on the acq loops
                # (eg during testing), and they might all be stopped, in which case
                # we can also just break.
                logger.debug("All acquisition loops have stopped")
                break

            # Update pbar
            if (datetime.now() - datetime_prev).total_seconds() > 1:
                total_sec = (datetime.now() - datetime_rec_start).seconds
                pct_prog = np.round(total_sec / recording_duration_s * 100, 2)
                print(
                    f"\rRecording Progress: {pct_prog}% ({total_sec} / {recording_duration_s} sec)",
                    end="",
                )
                datetime_prev = datetime.now()

    except KeyboardInterrupt:
        # This feels redundant, probably don't really need it
        logger.info("Keyboard interrupt received, stopping recording.")

    finally:
        # End the processes and close the microcontroller serial connection
        logger.info("Ending processes, this may take a moment...")
        if config["globals"]["microcontroller_required"]:
            if not finished:
                microcontroller.interrupt_acquisition()
            microcontroller.close()

        """ 
        TODO: This writer timeout is at risk of squashing the saving of videos if there's a huge buffer. 
        One images 5 min is enough but you never know... The tradeoff is that if the writer process hangs, 
        and this has no timeout, it will never close gracefully. 
        """
        end_processes(acquisition_loops, writers, display_proc, writer_timeout=300)

        logger.info("Processes ended")
        print("\rRecording Progress: 100%", end="")
        logger.info("Done.")

    return full_save_location, config


def reset_loggers():
    """Remove all handlers from all loggers and reset the root logger.

    This should be called right before the refactor_acquire_video function whenever
    the same python kernel is being used for more than one acquisition, e.g. in a notebook context.
    """
    # Remove handlers from all loggers
    for logger in logging.Logger.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):  # Guard against 'PlaceHolder' objects
            logger.handlers.clear()

    # Reset the root logger
    logging.getLogger().handlers.clear()
