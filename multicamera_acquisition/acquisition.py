from glob import glob
import logging
import multiprocessing as mp
import os
from os.path import join, exists
import traceback
from datetime import datetime, timedelta
from logging import StreamHandler
from logging.handlers import QueueListener
from pathlib import Path

import numpy as np
import yaml

from multicamera_acquisition.config import (
    create_full_camera_default_config,
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
        """Create multiprocessing events."""
        self.await_process = mp.Event()  # was previously "ready"
        self.await_main_thread = mp.Event()  # was previously "primed"
        self.stopped = mp.Event()

    def _continue_from_main_thread(self):
        """Tell the acquisition loop to continue
        (Called from the main thread)
        """
        self.await_main_thread.set()
        self.await_process.clear()  # reset this event so we can use it again

    def stop(self):
        self.stopped.set()

    def run(self):
        """Acquire frames. This is run when mp.Process.start() is called."""

        # Set up logging
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

        # Get the Camera object instance
        try:
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
        self.logger.debug(f"Waiting for main thread")
        self.await_main_thread.wait()

        # Once we get the go-ahead, tell the camera to start grabbing
        cam.start()

        # Once the camera is started grabbing, allow the main
        # thread to continue
        self.await_process.set()  # report to the main loop that the camera is ready

        # Get ready to record
        current_iter = 0
        n_frames_received = 0
        first_frame = False
        timeout = 1000 if self.fps is None else int(1000 / self.fps * 1.25)
        prev_timestamp = 0

        # Acquire frames until we receive the stop signal
        self.logger.debug("Ready to record")
        while not self.stopped.is_set():
            try:
                if first_frame:
                    # If this is the first frame, give a long time for serial to connect
                    data = cam.get_array(timeout=1000 * 60, get_timestamp=True)
                    first_frame = False
                    self.logger.debug("First frame received")
                    prev_timestamp = data[1]
                else:
                    data = cam.get_array(timeout=timeout, get_timestamp=True)

                # If we received a frame:
                if len(data) != 0:

                    # Increment the frame counter (distinct from number of while loop iterations)
                    n_frames_received += 1

                    # If this is an azure camera, we write the depth data to a separate queue
                    if self.camera_config["brand"] == "azure":
                        depth, ir, camera_timestamp = data

                        self.write_queue.put(
                            tuple([ir, camera_timestamp, n_frames_received])
                        )
                        self.write_queue_depth.put(
                            tuple([depth, camera_timestamp, n_frames_received])
                        )
                        if self.camera_config["display"]["display_frames"]:
                            if n_frames_received % self.display_every_n == 0:
                                self.display_queue.put(
                                    tuple(
                                        [
                                            depth[
                                                :: self.acq_config["downsample"],
                                                :: self.acq_config["downsample"],
                                            ],
                                            camera_timestamp,
                                            n_frames_received,
                                        ]
                                    )
                                )
                    else:
                        camera_timestamp = data[1]
                        data = data + tuple([n_frames_received])
                        self.write_queue.put(data)
                        if self.camera_config["display"]["display_frames"]:
                            if (
                                n_frames_received % self.acq_config["display_every_n"]
                                == 0
                            ):
                                data = (
                                    data[0][
                                        :: self.acq_config["downsample"],
                                        :: self.acq_config["downsample"],
                                    ],
                                    data[1],
                                    data[2],
                                )
                                self.display_queue.put(data)

                    # Check if we dropped any frames
                    delta_t = (camera_timestamp - prev_timestamp) / 1e6
                    if (
                        self.acq_config["dropped_frame_warnings"]
                        and delta_t > (timeout) * 1.25
                    ):
                        self.logger.warn(
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
                        self.logger.warn(
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
            f"Received {n_frames_received} many frames over {current_iter} iterations, {self.camera_config['name']}"
        )
        self.logger.debug(
            f"Writing empties to stop queue, {self.camera_config['name']}"
        )
        self.write_queue.put(tuple())  # empty tuple signals the writer to stop
        if self.write_queue_depth is not None:
            self.write_queue_depth.put(tuple())
        if self.display_queue is not None:
            self.display_queue.put(tuple())

        # Close the camera
        self.logger.debug(f"Closing camera {self.camera_config['name']}")
        cam.close()
        self.logger.debug("Camera closed")

        # Report that the process has stopped
        self.logger.debug(f"Acq loop for {self.camera_config['name']} is finished.")


def generate_full_config(camera_lists):
    full_config = {}
    acquisition_config = AcquisitionLoop.default_acq_loop_config().copy()
    microcontroller_config = Microcontroller.default_microcontroller_config().copy()
    # camera, camera writer, camera display config
    full_camera_config = create_full_camera_default_config(camera_lists)
    full_config["acq_loop"] = acquisition_config
    full_config["microcontroller"] = microcontroller_config
    full_config["cameras"] = full_camera_config

    # write to file
    with open("full_config.yaml", "w") as f:
        yaml.dump(full_config, f)
    return full_config


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
            # acquisition_loop.join(timeout=1)
            acquisition_loop.join(timeout=60 * 60)

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

    video_file_name : Path
        The path to the video file.

    final_config: dict
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

    # print(full_save_location)
    if exists(full_save_location) and len(glob(join(full_save_location, "*.mp4"))) > 0 and not overwrite:
        raise ValueError(
            f"Save location {full_save_location} already exists with at least one MP4. If you want save into this dir anyways and risk overwriting, set overwrite to True!"
        )
    os.makedirs(full_save_location, exist_ok=True)
    basename = str(
        full_save_location / recording_name
    )  # /path/to/my/recording_name/recording_name, which will have strings appended to become, eg, /path/to/my/recording_name/recording_name.top.mp4
    
    logger.debug(f"Have good save location {full_save_location}")

    # Load the config file if it exists
    if isinstance(config, str) or isinstance(config, Path):
        config = load_config(config)
    else:
        assert isinstance(config, dict)

    # Add the display params to the config
    final_config = config

    # Resolve camera device indices
    device_index_dict = resolve_device_indices(final_config)

    # Check that the config is valid
    validate_recording_config(final_config, logging_level)

    # Save the config file before starting the recording
    config_filepath = Path(basename + ".recording_config.yaml")
    save_config(config_filepath, final_config)

    # Find the microcontroller to be used for triggering
    if final_config["globals"]["microcontroller_required"]:
        logger.info("Finding microcontroller...")
        microcontroller = Microcontroller(basename, final_config)
        microcontroller.open_serial_connection()

    # TODO: triggerdata file

    # Create the various processes
    # TODO: refactor these into one "running processes" dict or sth like that
    logger.info("Opening subprocesses and cameras, this may take a moment...")
    writers = []
    acquisition_loops = []
    display_queues = []
    camera_list = []
    display_ranges = []

    try:
        for camera_name, camera_dict in final_config["cameras"].items():
            # Create a writer queue
            write_queue = mp.Queue()

            # Generate file names
            if append_camera_serial:
                cam_append_str = f".{camera_dict['name']}.{camera_dict['id']}.mp4"
            else:
                cam_append_str = f".{camera_dict['name']}.mp4"
            video_file_name = Path(basename + cam_append_str)
            metadata_file_name = Path(
                basename + cam_append_str.replace(".mp4", ".metadata.csv")
            )

            # Get a writer process
            writer = get_writer(
                write_queue,
                video_file_name,
                metadata_file_name,
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
                display_queue = mp.Queue()
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
                acq_loop_config=final_config["acq_loop"],
                logger_queue=logger_queue,
                logging_level=logging_level,
                process_name=f"{camera_name}_acqLoop",
                fps=final_config["globals"]["fps"],
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
            config=final_config["rt_display"],
        )
        display_proc.start()
    else:
        display_proc = None

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
    if final_config["globals"]["microcontroller_required"]:
        logger.info("Starting microcontroller...")
        microcontroller.start_acquisition(recording_duration_s)

    # Wait for the specified duration
    try:
        print(f"\rRecording Progress: 0%", end="")

        datetime_prev = datetime.now()
        datetime_rec_start = datetime_prev
        endtime = datetime_prev + timedelta(seconds=recording_duration_s + 10)

        while datetime.now() < endtime:
            if final_config["globals"]["microcontroller_required"]:
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
                pct_prog = np.round(
                    (datetime.now() - datetime_rec_start).seconds
                    / recording_duration_s
                    * 100,
                    2,
                )
                total_sec = (datetime.now() - datetime_rec_start).seconds
                print(
                    f"\rRecording Progress: {pct_prog}% ({total_sec} / {recording_duration_s} sec)",
                    end="",
                )
                datetime_prev = datetime.now()

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, stopping recording.")

    finally:
        # End the processes and close the microcontroller serial connection
        logger.info("Ending processes, this may take a moment...")
        end_processes(acquisition_loops, writers, display_proc, writer_timeout=300)
        logger.info("Processed ended")
        print("\rRecording Progress: 100%", end="")
        if final_config["globals"]["microcontroller_required"]:
            if not finished:
                microcontroller.interrupt_acquisition()
            microcontroller.close()
        logger.info("Done.")

    return full_save_location, video_file_name, final_config


def reset_loggers():
    # Remove handlers from all loggers
    for logger in logging.Logger.manager.loggerDict.values():
        if isinstance(logger, logging.Logger):  # Guard against 'PlaceHolder' objects
            logger.handlers.clear()

    # Reset the root logger
    logging.getLogger().handlers.clear()
