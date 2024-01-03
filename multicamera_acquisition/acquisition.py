import csv
import logging
import multiprocessing as mp
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import serial

from tqdm import tqdm
from multicamera_acquisition.interfaces.camera_base import get_camera
from multicamera_acquisition.writer import get_writer
from multicamera_acquisition.config.config import (
    load_config,
    save_config,
    validate_recording_config,
    add_rt_display_params_to_config,
)
from multicamera_acquisition.interfaces.config import create_full_camera_default_config, partial_config_from_camera_list
from multicamera_acquisition.paths import prepare_rec_dir

# from multicamera_acquisition.interfaces.camera_azure import AzureCamera
# from multicamera_acquisition.interfaces.arduino import (
    # find_serial_ports, packIntAsLong, wait_for_serial_confirmation)
# from multicamera_acquisition.visualization import MultiDisplay
# from multicamera_acquisition.writer import Writer


class AcquisitionLoop(mp.Process):
    """A process that acquires images from a camera
    and writes them to a queue.
    """

    def __init__(
        self,
        write_queue,
        display_queue,
        write_queue_depth=None,
        camera_config=None,
        acq_loop_config=None,
    ):
        """
        Parameters
        ----------
        write_queue : multiprocessing.Queue
            A queue to which frames will be written.

        display_queue : multiprocessing.Queue
            A queue from which frames will be read for display.

        write_queue_depth : multiprocessing.Queue (default: None)
            A queue to which depth frames will be written (azure only).

        camera_config : dict (default: None)
            A config dict for the Camera.
            If None, an error will be raised.

        acq_loop_config : dict (default: None)
            A config dict for the AcquisitionLoop.
            If None, the default config will be used.
        """
        super().__init__()

        # Save values
        self.write_queue = write_queue
        self.display_queue = display_queue
        self.write_queue_depth = write_queue_depth
        self.camera_config = camera_config

        # Get config
        if acq_loop_config is None:
            self.acq_config = self.default_acq_loop_config()
        else:
            self.acq_config = acq_loop_config

        # Check for Nones in camera / writer configs
        # The idea here is that by now, we should have already
        # resolved any need to use default configs.
        if self.camera_config is None:
            raise ValueError("Camera config cannot be None")

        # Set up events for mp coordination
        self._create_mp_events()

    @staticmethod
    def default_acq_loop_config():
        """Get the default config for the acquisition loop.
        """
        return {
            "frame_timeout": 1000,
            "display_frames": False,
            "display_every_n": 1,
            "dropped_frame_warnings": False,
            "max_frames_to_acqure": None,
        }

    def _create_mp_events(self):
        """Create multiprocessing events.
        """
        self.await_process = mp.Event()  # was previously "ready"
        self.await_main_thread = mp.Event()  # was previously "primed"
        self.stopped = mp.Event()

    def _continue_from_main_thread(self):
        """ Tell the acquisition loop to continue 
        (Called from the main thread)
        """
        self.await_main_thread.set()
        self.await_process.clear()  # reset this event so we can use it again

    def stop(self):
        self.stopped.set()

    def run(self):
        """Acquire frames. This is run when mp.Process.start() is called.
        """

        # Get the Camera object instance
        cam = get_camera(
            brand=self.camera_config["brand"],
            id=self.camera_config["id"],
            config=self.camera_config,
        )

        # Actually open / initialize the connection to the camera
        cam.init()

        # Report that the process has initialized the camera
        self.await_process.set()  # report to the main loop that the camera is ready

        # Here, the main thread will loop through all the acq loop objects
        # and start each camera. The main thread will wait for 
        # each acq loop to report that it has started its camera.

        # Wait for the main thread to get to the for-loop
        # where it will then wait for the camera to start
        self.await_main_thread.wait()

        # Once we get the go-ahead, tell the camera to start grabbing
        cam.start()

        # Once the camera is started grabbing, allow the main
        # thread to continue
        self.await_process.set()  # report to the main loop that the camera is ready

        current_frame = 0
        first_frame = False
        while not self.stopped.is_set():
            try:
                if first_frame:
                    # If this is the first frame, give time for serial to connect
                    data = cam.get_array(timeout=10000, get_timestamp=True)
                    first_frame = False
                else:
                    data = cam.get_array(timeout=self.acq_config["frame_timeout"], get_timestamp=True)

                if len(data) != 0:

                    # If this is an azure camera, we write the depth data to a separate queue
                    if self.camera_config["brand"] == "azure":
                        depth, ir, camera_timestamp = data

                        self.write_queue.put(
                            tuple([ir, camera_timestamp, current_frame])
                        )
                        self.write_queue_depth.put(
                            tuple([depth, camera_timestamp, current_frame])
                        )
                        if self.acq_config["display_frames"]:
                            if current_frame % self.display_every_n == 0:
                                self.display_queue.put(
                                    tuple([depth, camera_timestamp, current_frame])
                                )
                    else:
                        data = data + tuple([current_frame])
                        self.write_queue.put(data)
                        if self.acq_config["display_frames"]:
                            if current_frame % self.acq_config["display_every_n"] == 0:
                                self.display_queue.put(data)

            except Exception as e:
                # if a frame was dropped, log the lost frame and contiue
                if type(e).__name__ == "SpinnakerException":
                    pass
                elif type(e).__name__ == "TimeoutException":
                    logging.log(logging.DEBUG, f"{self.brand}:{e}")
                    pass
                else:
                    raise e
                if self.config["dropped_frame_warnings"]:
                    warnings.warn(
                        "Dropped {} frame on #{}: \n{}".format(
                            current_frame,
                            cam.serial_number,
                            type(e).__name__,  # , str(e)
                        )
                    )
            current_frame += 1
            if self.acq_config["max_frames_to_acqure"] is not None:
                if current_frame >= self.acq_config["max_frames_to_acqure"]:
                    break

        # Once the stop signal is received, stop the writer and dispaly processes
        logging.debug(f"Writing empties to stop queue, {self.camera_config['name']}")
        self.write_queue.put(tuple())
        if self.write_queue_depth is not None:
            self.write_queue_depth.put(tuple())
        if self.display_queue is not None:
            self.display_queue.put(tuple())

        # Close the camera
        logging.log(logging.INFO, f"Closing camera {self.camera_config['name']}")
        cam.close()

        logging.debug(f"Acquisition run finished, {self.camera_config['name']}")


def end_processes(acquisition_loops, writers, disp, writer_timeout=60):
    """ Use the stop() method to end the acquisition loops, writers, and display
    processes, escalating to terminate() if necessary.
    """

    # End acquisition loop processes
    for acquisition_loop in acquisition_loops:
        if acquisition_loop.is_alive():
            logging.log(
                logging.DEBUG,
                f"stopping acquisition loop ({acquisition_loop.camera_config['name']})",
            )

            # Send a stop signal to the process
            acquisition_loop.stop()

            # Wait for the process to finish
            logging.log(
                logging.DEBUG,
                f"joining acquisition loop ({acquisition_loop.camera_config['name']})",
            )
            acquisition_loop.join(timeout=1)

            # If still alive, terminate it
            if acquisition_loop.is_alive():
                # debug: notify user we had to terminate the acq loop
                logging.debug("Terminating acquisition loop (join timed out)")
                acquisition_loop.terminate()

    # End writer processes
    for writer in writers:
        if writer.is_alive():
            writer.join(timeout=writer_timeout)

    # Debug: printer the writer's exitcode
    logging.debug(f"Writer exitcode: {writer.exitcode}")

    # End display processes
    if disp is not None:
        # TODO figure out why display.join hangs when there is >1 azure
        if disp.is_alive():
            disp.join(timeout=1)
        if disp.is_alive():
            disp.terminate()


def refactor_acquire_video(
        save_location, 
        config,
        recording_duration_s=60, 
        append_datetime=True, 
        append_camera_serial=False,
        overwrite=False
):
    """Acquire video from multiple, synchronized cameras.

    Parameters
    ----------
    save_location : str or Path
        The directory in which to save the recording.

    config : dict or str or Path
        A dict containing the recording config, or a filepath to a yaml file
        containing the recording config.
        # TODO: incl rt_display_params

    recording_duration_s : int (default: 60)
        The duration of the recording in seconds.

    append_datetime : bool (default: True)
        Whether to further nest the recording in a subfolder named with the
        date and time.

    append_camera_serial : bool (default: True)
        Whether to append the camera serial number to the file name.

    overwrite : bool (default: False)
        Whether to overwrite the save location if it already exists.

    Returns
    -------
    save_location : Path
        The directory in which the recording was saved.

    config: dict
        The final recording config used.

    Examples
    --------
    A full config file follows the following rough layout:

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
        arduino:
            [list of arduino params]

    For example, here is a minimal config file for a single camera without an arduino:

        cameras:
            top:
                name: top
                brand: basler
                id: "12345678"  # ie the serial number, as a string
                fps: 30
                gain: 6
                exposure_time: 1000
                display: True
                roi: null  # or an roi to crop the image
                trigger:
                    short_name: continuous  # convenience attr for no-trigger acquisition
                writer:
                    codec: h264
                    fmt: YUV420
                    fps: 30
                    gpu: null
                    max_video_frames: 2592000
                    multipass: '0'
                    pixel_format: gray8
                    preset: P1
                    profile: high
                    tuning_info: ultra_low_latency
        acq_loop:
            frame_timeout: 1000
            display_frames: False
            display_every_n: 4
            dropped_frame_warnings: False
            max_frames_to_acqure: null
        rt_display:
            display_downsample: 4
            display_framerate: 30
            display_range: [0, 1000]
    """

    # Create the recording directory
    save_location = prepare_rec_dir(save_location, append_datetime=append_datetime, overwrite=overwrite)

    # Load the config file if it exists
    if isinstance(config, str) or isinstance(config, Path):
        config = load_config(config)
    else:
        assert isinstance(config, dict)

    # Add the display params to the config
    # final_config = add_rt_display_params_to_config(config, rt_display_params)
    final_config = config

    # TODO: add arduino configs

    # Check that the config is valid
    validate_recording_config(final_config)

    # Save the config file before starting the recording
    config_filepath = save_location / "recording_config.yaml"
    save_config(config_filepath, final_config)

    # (...other stuff happens, eg arduino...)
    # TODO: implement arduino stuff here

    # Create the various processes
    writers = []
    acquisition_loops = []
    # display_queues = [] # TODO: implement display queues

    for camera_name, camera_dict in final_config["cameras"].items():

        # Create a writer queue
        write_queue = mp.Queue()

        # Generate file names
        if append_camera_serial:
            video_file_name = save_location / f"{camera_name}.{camera_dict['id']}.mp4"
            metadata_file_name = save_location / f"{camera_name}.{camera_dict['id']}.metadata.csv"
        else:
            video_file_name = save_location / f"{camera_name}.mp4"
            metadata_file_name = save_location / f"{camera_name}.metadata.csv"

        # Get a writer process
        writer = get_writer(
            write_queue,
            video_file_name,
            metadata_file_name,
            writer_type=camera_dict["writer"]["type"],
            config=camera_dict["writer"],
        )

        # Get a second writer process for depth if needed
        if camera_dict["brand"] == "azure":
            write_queue_depth = mp.Queue()
            video_file_name_depth = save_location / f"{camera_name}.depth.avi"
            metadata_file_name_depth = save_location / f"{camera_name}.metadata.depth.csv"
            writer_depth = get_writer(
                write_queue_depth,
                video_file_name_depth,
                metadata_file_name_depth,
                writer_type=camera_dict["writer"]["type"],
                config=camera_dict["writer_depth"], # TODO: make a separate writer_depth config for depth
            )
        else:
            write_queue_depth = None

        # Create an acquisition loop process
        acquisition_loop = AcquisitionLoop(
            write_queue=write_queue,
            display_queue=None,
            write_queue_depth=write_queue_depth,
            camera_config=camera_dict,
            acq_loop_config=final_config["acq_loop"],
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
        acquisition_loop.await_process.wait()

    # TODO: display queues here

    # Wait for the acq loop processes to start their cameras
    for acquisition_loop in acquisition_loops:
        acquisition_loop._continue_from_main_thread()
        acquisition_loop.await_process.wait()

    # TODO: arduino startup stuff here

    # Wait for the specified duration
    # (while current time is less than initial time + recording_duration_s)
    try:
        pbar = tqdm(total=recording_duration_s, desc="recording progress (s)")
        # how long to record
        datetime_prev = datetime.now()
        endtime = datetime_prev + timedelta(seconds=recording_duration_s)
        while datetime.now() < endtime:

            # Update pbar
            if (datetime.now() - datetime_prev).seconds > 0:
                pbar.update((datetime.now() - datetime_prev).seconds)
                datetime_prev = datetime.now()

    except (KeyboardInterrupt) as e:
        pass

    # End the processes
    pbar.close()
    print("Ending processes, this may take a moment...")
    end_processes(acquisition_loops, writers, None, writer_timeout=300)
    print("Done.")

    return save_location, final_config


"""
pesudo code for refactor of acquire_video

-- first, get the desired recording dir from the user and make it safely.
-- in separate funcs, generate a config file for the recording from the user-provided camera list. 
    This should grab the default configs for each camera, and then overwrite them with any user-provided configs.
    This should also check that the user-provided configs are valid (e.g. framerate is a multiple of display_framerate).
    This will get saved in the recording directory.
    -- There should also be an option for the user to point to a "master config" for a certain experiment, which 
    will allow easy reproducibility of experiments (ie reuse identical configs each day). A copy of the config
    should be saved in the recording directory anyways.
-- once we have good configs, we will start the actual recording funcs.
-- first, check if we need an arduino; if we do, find one and connect to it, raising err if we can't find it.
-- then create the writer / acquisition / display loops, hopefully in a more succinct way than it's being done now
-- then, as it is now, start the acquisition loops (which will wait for the arduino to start recording)
    , then start the writer and display loops, send a msg to the arduino, and then wait for the arduino to finish recording 
    while handling errors appropriately.
"""


def acquire_video(
    save_location,
    camera_list,
    recording_duration_s,
    frame_timeout=None,
    azure_recording=False,
    framerate=30,
    azure_framerate=30,
    display_framerate=30,
    serial_timeout_duration_s=0.1,
    display_downsample=4,
    overwrite=False,
    append_datetime=True,
    append_camera_serial=True,
    verbose=True,
    dropped_frame_warnings=False,
    n_input_trigger_states=4,
    max_video_frames="default",  # after this many frames, a new video file will be created
    ffmpeg_options={},
    arduino_args=[],
):
    if azure_framerate != 30:
        raise ValueError("Azure framerate must be 30")

    if azure_recording:
        # ensure that framerate is a multiple of azure_framerate
        if framerate % azure_framerate != 0:
            raise ValueError("Framerate must be a multiple of azure_framerate")

    # ensure that framerate is a multiple of display_framerate
    if framerate % display_framerate != 0:
        raise ValueError("Framerate must be a multiple of display_framerate")

    exp_times = [
        cd["exposure_time"] for cd in camera_list if "exposure_time" in cd.keys()
    ]
    # if not all(exp <= 1000 for exp in exp_times):
    #    raise ValueError("Max exposure time is 1000 microseconds")

    if max_video_frames == "default":
        # set max video frames to 1 hour
        max_video_frames = framerate * 60 * 60

    if "fps" not in ffmpeg_options:
        ffmpeg_options["fps"] = framerate

    if verbose:
        logging.log(logging.INFO, "Checking cameras...")

    camera_brands = np.array([i["brand"] for i in camera_list])
    # if there are cameras that are not flir or basler, raise an error
    for i in camera_brands:
        if i not in ["flir", "basler", "azure", "lucid"]:
            raise ValueError(
                "Camera brand must be either 'flir' or 'basler', azure, not {}".format(
                    i
                )
            )
    # if there are both flir and basler cameras, make sure that the basler cameras are initialized after the flir cameras
    if "flir" in camera_brands and "basler" in camera_brands:
        if np.any(
            np.where(camera_brands == "basler")[0][0]
            < np.max(np.where(camera_brands == "flir")[0])
        ):
            warnings.warn(
                """A bug in the code requies Basler cameras to be initialized after Flir cameras. Rearranging camera order.
                """
            )
            # swap the order of the cameras so that flir cameras are before basler cameras
            camera_list = [camera_list[i] for i in np.argsort(camera_brands)[::-1]]

    # determine the frequency at which to output frames to the display
    display_frequency = int(framerate / display_framerate)
    if display_frequency < 1:
        display_frequency = 1

    # get Path of save location
    if type(save_location) != Path:
        save_location = Path(save_location)

    # create a subfolder for the current datetime
    if append_datetime:
        date_str = datetime.now().strftime("%y-%m-%d-%H-%M-%S-%f")
        save_location = save_location / date_str

    # ensure that a directory exists to save data in
    save_location.mkdir(parents=True, exist_ok=True)
    print(f"Save location exists: {save_location.exists()}")
    if save_location.exists() == False:
        raise ValueError(f"Save location {save_location} does not exist")

    triggerdata_file = save_location / "triggerdata.csv"
    if triggerdata_file.exists() and (overwrite == False):
        raise FileExistsError(f"CSV file {triggerdata_file} already exists")

    if verbose:
        logging.log(logging.INFO, f"Initializing Arduino...")

    # Find the arduino to be used for triggering
    # TODO: allow user to specify a port
    ports = find_serial_ports()
    found_arduino = False
    for port in ports:
        with serial.Serial(port=port, timeout=0.1) as arduino:
            try:
                wait_for_serial_confirmation(
                    arduino, expected_confirmation="Waiting...", seconds_to_wait=2
                )
                found_arduino = True
                break
            except ValueError:
                continue
    if found_arduino is False:
        raise RuntimeError("Could not find waiting arduino to do triggers!")
    else:
        logging.info(f"Using port {port} for arduino.")
    arduino = serial.Serial(port=port, timeout=serial_timeout_duration_s)

    # delay recording to allow serial connection to connect
    sleep_duration = 2
    logging.log(
        logging.INFO, f"Waiting {sleep_duration}s to wait for arduino to connect..."
    )
    time.sleep(sleep_duration)

    # create a triggerdata file
    with open(triggerdata_file, "w") as triggerdata_f:
        triggerdata_writer = csv.writer(triggerdata_f)
        triggerdata_writer.writerow(
            ["pulse_id", "arduino_ms"]
            + [f"flag_{i}" for i in range(n_input_trigger_states)]
        )

    if verbose:
        logging.log(logging.INFO, "Initializing cameras...")
    # initialize cameras
    writers = []
    acquisition_loops = []
    display_queues = []
    camera_names = []
    display_ranges = []  # range for displaying (for azure mm)

    num_azures = len([v for v in camera_list if "azure" in v["brand"]])
    num_baslers = len(camera_list) - num_azures

    # create acquisition loops
    for camera_dict in camera_list:
        name = camera_dict["name"]
        serial_number = camera_dict["serial"]

        camera_framerate = (
            azure_framerate if camera_dict["brand"] == "azure" else framerate
        )

        ffmpeg_options = {}
        for key in ["gpu", "quality"]:
            if key in camera_dict:
                ffmpeg_options[key] = camera_dict[key]

        if "display" in camera_dict.keys():
            display_frames = camera_dict["display"]
        else:
            display_frames = False

        if verbose:
            logging.log(logging.INFO, f"Camera {name}...")

        # create a writer queue
        if camera_dict["brand"] == "lucid":
            if append_camera_serial:
                video_file = save_location / f"{name}.{serial_number}.avi"
                metadata_file = save_location / f"{name}.{serial_number}.metadata.csv"
            else:
                video_file = save_location / f"{name}.avi"
                metadata_file = save_location / f"{name}.metadata.csv"

            if video_file.exists() and (overwrite == False):
                raise FileExistsError(f"Video file {video_file} already exists")

            write_queue = mp.Queue()
            writer = Writer(
                queue=write_queue,
                video_file_name=video_file,
                metadata_file_name=metadata_file,
                camera_serial=serial_number,
                fps=camera_framerate,
                camera_name=name,
                camera_brand=camera_dict["brand"],
                max_video_frames=max_video_frames,
                ffmpeg_options=ffmpeg_options,
                depth=True,  # uses 16 bit depth
            )
        else:
            if append_camera_serial:
                video_file = save_location / f"{name}.{serial_number}.mp4"
                metadata_file = save_location / f"{name}.{serial_number}.metadata.csv"
            else:
                video_file = save_location / f"{name}.mp4"
                metadata_file = save_location / f"{name}.metadata.csv"

            if video_file.exists() and (overwrite == False):
                raise FileExistsError(f"Video file {video_file} already exists")

            write_queue = mp.Queue()
            writer = Writer(
                queue=write_queue,
                video_file_name=video_file,
                metadata_file_name=metadata_file,
                camera_serial=serial_number,
                fps=camera_framerate,
                camera_name=name,
                camera_brand=camera_dict["brand"],
                max_video_frames=max_video_frames,
                ffmpeg_options=ffmpeg_options,
            )

        if camera_dict["brand"] == "azure":
            # create asecond write queue for the depth data
            # create a writer queue
            if append_camera_serial:
                video_file_depth = save_location / f"{name}.{serial_number}.depth.avi"
                metadata_file = (
                    save_location / f"{name}.{serial_number}.metadata.depth.csv"
                )
            else:
                video_file_depth = save_location / f"{name}.depth.avi"
                metadata_file = save_location / f"{name}.metadata.depth.csv"

            write_queue_depth = mp.Queue()
            writer_depth = Writer(
                queue=write_queue_depth,
                video_file_name=video_file_depth,
                metadata_file_name=metadata_file,
                camera_serial=serial_number,
                camera_name=name,
                fps=camera_framerate,
                camera_brand=camera_dict["brand"],
                max_video_frames=max_video_frames,
                ffmpeg_options=ffmpeg_options,
                depth=True,
            )

            cam = get_camera(**camera_dict)

        else:
            write_queue_depth = None
            cam = None

        display_queue = None
        if display_frames:
            # create a writer queue
            display_queue = mp.Queue()
            camera_names.append(name)
            if "display_range" in camera_dict:
                display_ranges.append(camera_dict["display_range"])
            else:
                display_ranges.append(None)
            display_queues.append(display_queue)

        # prepare the acuqisition loop in a separate thread
        acquisition_loop = AcquisitionLoop(
            write_queue=write_queue,
            write_queue_depth=write_queue_depth,
            display_queue=display_queue,
            display_frames=display_frames,
            display_frequency=display_frequency,
            dropped_frame_warnings=dropped_frame_warnings,
            frame_timeout=frame_timeout,
            cam=cam,
            **camera_dict,
        )

        # initialize acquisition
        writer.start()
        writers.append(writer)
        if camera_dict["brand"] == "azure":
            writer_depth.start()
            writers.append(writer_depth)

        acquisition_loop.start()
        acquisition_loop.await_process.wait()  # blocks until the acq loop reports that it is ready
        acquisition_loops.append(acquisition_loop)
        if verbose:
            logging.info(f"Initialized {name} ({serial_number})")

    if len(display_queues) > 0:
        # create a display process which recieves frames from the acquisition loops
        disp = MultiDisplay(
            display_queues,
            camera_names,
            display_downsample=display_downsample,
            display_ranges=display_ranges,
        )
        disp.start()
    else:
        disp = None

    if verbose:
        logging.log(logging.INFO, f"Preparing acquisition loops")

    # prepare acquisition loops
    for acquisition_loop in acquisition_loops:
        # set camera state to ready and primed
        acquisition_loop.prime()
        # Don't initialize until all cameras are ready
        acquisition_loop.ready.wait()

    if verbose:
        logging.log(logging.INFO, f"Telling arduino to start recording")

    """ TODO 
    We are currently hardcoding certain values in the arduino code that should instead be sent here.
    In particular, the basler framerate, the number of basler cameras, and the number of azures. 
    It would also be possible to send the pins that are used for the triggers instead of hardcoding them.
    """
    # Tell the arduino to start recording by sending along the recording parameters
    inv_framerate = int(np.round(1e6 / framerate, 0))
    # TODO: 600 and 1575 hardcoded
    # const_mult = np.ceil((inv_framerate - 600) / 1575).astype(int)
    if azure_recording:
        num_cycles = int(recording_duration_s * azure_framerate)
    else:
        num_cycles = int(recording_duration_s * framerate)

    logging.log(
        logging.DEBUG, f"Inverse framerate: {inv_framerate}; num cycles: {num_cycles}"
    )
    msg = b"".join(
        map(
            packIntAsLong,
            (
                num_cycles,
                inv_framerate,
                # const_mult,
                # num_azures,
                # num_baslers,
                *arduino_args,
            ),
        )
    )
    arduino.write(msg)

    # Run acquision
    try:
        confirmation = wait_for_serial_confirmation(
            arduino, expected_confirmation="Start", seconds_to_wait=10
        )
    except:
        # kill everything if we can't get confirmation
        end_processes(acquisition_loops, writers, disp)
        return save_location, camera_list

    if verbose:
        logging.log(logging.INFO, f"Starting Acquisition...")

    try:
        # while current time is less than initial time + recording_duration_s
        pbar = tqdm(total=recording_duration_s, desc="recording progress (s)")
        # how long to record
        datetime_prev = datetime.now()
        endtime = datetime_prev + timedelta(seconds=recording_duration_s + 10)
        while datetime.now() < endtime:
            confirmation = arduino.readline().decode("utf-8").strip("\r\n")
            if len(confirmation) > 0:
                print(confirmation)
            if confirmation == "Finished":
                break
            if (datetime.now() - datetime_prev).seconds > 0:
                pbar.update((datetime.now() - datetime_prev).seconds)
                datetime_prev = datetime.now()
            # save input data flags
            if len(confirmation) > 0:
                # print(confirmation)
                if confirmation[:7] == "input: ":
                    with open(triggerdata_file, "a") as triggerdata_f:
                        triggerdata_writer = csv.writer(triggerdata_f)
                        states = confirmation[7:].split(",")[:-2]
                        frame_num = confirmation[7:].split(",")[-2]
                        arduino_clock = confirmation[7:].split(",")[-1]
                        triggerdata_writer.writerow([frame_num, arduino_clock] + states)
                if verbose:
                    logging.log(logging.INFO, f"confirmation")

        # wait for a confirmation of being finished
        if confirmation == "Finished":
            print("Confirmation recieved: {}".format(confirmation))
        else:
            logging.log(logging.INFO, "Waiting for finished confirmation")
            try:
                confirmation = wait_for_serial_confirmation(
                    arduino, expected_confirmation="Finished", seconds_to_wait=10
                )
            except ValueError as e:
                logging.log(logging.WARN, e)

        if verbose:
            logging.log(logging.INFO, f"Closing")

        # Close the arduino just in case
        arduino.close()

        # TODO wait until all acquisition loops are finished
        #   the proper way to do this would be to use a event.wait()
        #   for each camera, to wait until it has no more frames to grab
        #   (except in the case of azure, where it will always be able) to
        #   grab more frames because it is not locked to the arduino pulse.
        #   for now, I've just added a 5 second sleep after the arduino is 'finished'
        #   which should be enough time for the cameras to finish grabbing frames
        time.sleep(5)

    # unless there is a keyboard interrupt, in which case we should catch the error and still
    #   return the save location
    except (KeyboardInterrupt, serial.SerialException) as e:
        pass

    end_processes(acquisition_loops, writers, disp)

    pbar.close()

    return save_location, camera_list
