import csv
import logging
import multiprocessing as mp
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import serial
import yaml
from tqdm import tqdm

from multicamera_acquisition.configs.default_display_config import \
    default_display_config
from multicamera_acquisition.interfaces.camera_basler import BaslerCamera
# from multicamera_acquisition.interfaces.camera_azure import AzureCamera
# from multicamera_acquisition.interfaces.arduino import (
    # find_serial_ports, packIntAsLong, wait_for_serial_confirmation)
# from multicamera_acquisition.visualization import MultiDisplay
# from multicamera_acquisition.writer import Writer

ALL_CAM_PARAMS = [
    "name",
    "brand",
    "serial",
    "exposure_time",
    "display",
]

ALL_WRITER_PARAMS = [
    "gpu",
    "quality",
]

ALL_DISPLAY_PARAMS = [
    "display_range",  # (min, max) for display colormap
]

# Since we will match params 1:1 with the user-provided camera list, we need to
# ensure that the param names are never redundant.
# TODO: could decide to un-flatten the camera list, which would also solve this.
assert all([param not in ALL_CAM_PARAMS for param in ALL_WRITER_PARAMS])
assert all([param not in ALL_CAM_PARAMS for param in ALL_DISPLAY_PARAMS])
assert all([param not in ALL_WRITER_PARAMS for param in ALL_DISPLAY_PARAMS])


class AcquisitionLoop(mp.Process):
    """A process that acquires images from a camera
    and writes them to a queue.
    """

    def __init__(
        self,
        write_queue,
        display_queue,
        brand="flir",
        frame_timeout=1000,
        display_frames=False,
        display_frequency=1,
        dropped_frame_warnings=False,
        write_queue_depth=None,
        cam=None,
        **camera_params,
    ):
        """
        Parameters
        ----------
        write_queue : multiprocessing.Queue
            A queue to which frames will be written.
        display_queue : multiprocessing.Queue
            A queue from which frames will be read for display.
        brand : str
            The brand of camera to use.  Currently 'flir' and 'basler' are supported.
        frame_timeout : int
            The number of milliseconds to wait for a frame before timing out.
        display_frames : bool
            If True, frames will be displayed.
        display_frequency : int
            The number of frames to skip between displaying frames.
        dropped_frame_warnings: bool
            Whether to issue a warning when frame grabbing times out
        **camera_params
            Keyword arguments to pass to the camera interface.
        """
        super().__init__()

        self.ready = mp.Event()
        self.primed = mp.Event()
        self.stopped = mp.Event()
        self.write_queue = write_queue
        self.display_queue = display_queue
        self.camera_params = camera_params
        self.brand = brand
        self.frame_timeout = frame_timeout
        self.display_frames = display_frames
        self.display_frequency = display_frequency
        self.dropped_frame_warnings = dropped_frame_warnings
        self.write_queue_depth = write_queue_depth
        self.cam = cam

    def stop(self):
        self.stopped.set()

    def prime(self):
        self.ready.clear()
        self.primed.set()

    def run(self):
        """Acquire frames. This is run when mp.Process.start() is called.
        """

        # get the camera if it hasn't been passed in (e.g. for azure)
        if self.cam is None:
            try:
                if "serial" in self.camera_params:
                    self.camera_params["index"] = self.camera_params["serial"]
                cam = get_camera(brand=self.brand, index=self.camera_params["index"])
            except Exception as e:
                logging.log(logging.ERROR, f"{self.brand}:{e}")
                raise e
        else:
            cam = self.cam
        self.ready.set()  # report to the main loop that the camera is ready
        self.primed.wait()  # wait until the main loop is ready to start

        # tell the camera to start grabbing
        cam.start()
        # once the camera is started grabbing, allow the main
        # process to continue
        self.ready.set()  # report to the main loop that the camera is ready

        current_frame = 0
        initialized = False
        while not self.stopped.is_set():
            try:
                # debug write getting frame
                # logging.debug(
                #    f"Getting frame, camera, {self.camera_params['name']}, current frame: {current_frame}"
                # )
                if initialized:
                    data = cam.get_array(timeout=self.frame_timeout, get_timestamp=True)
                else:
                    # if this is the first frame, give time for serial to connect
                    data = cam.get_array(timeout=10000, get_timestamp=True)
                # logging.debug(
                #    f"Got frame, camera, {self.camera_params['name']}, current frame: {current_frame}"
                # )
                if len(data) != 0:
                    # if this is an azure camera, we write the depth data to a separate queue
                    if self.brand == "azure":
                        depth, ir, camera_timestamp = data

                        self.write_queue.put(
                            tuple([ir, camera_timestamp, current_frame])
                        )
                        self.write_queue_depth.put(
                            tuple([depth, camera_timestamp, current_frame])
                        )
                        if self.display_frames:
                            if current_frame % self.display_frequency == 0:
                                self.display_queue.put(
                                    tuple([depth, camera_timestamp, current_frame])
                                )
                    else:
                        data = data + tuple([current_frame])
                        self.write_queue.put(data)
                        if self.display_frames:
                            if current_frame % self.display_frequency == 0:
                                self.display_queue.put(data)
                initialized = True

            except Exception as e:
                # if a frame was dropped, log the lost frame and contiue
                if type(e).__name__ == "SpinnakerException":
                    pass
                elif type(e).__name__ == "TimeoutException":
                    logging.log(logging.DEBUG, f"{self.brand}:{e}")
                    pass
                else:
                    raise e
                if self.dropped_frame_warnings:
                    warnings.warn(
                        "Dropped {} frame on #{}: \n{}".format(
                            current_frame,
                            cam.serial_number,
                            type(e).__name__,  # , str(e)
                        )
                    )
            # logging.debug(
            #    f"finished loop, {self.camera_params['name']}, current frame: {current_frame}, stopped: {self.stopped.is_set()}"
            # )
            current_frame += 1

        logging.debug(f"Writing empties to queue, {self.camera_params['name']}")

        if self.brand == "azure":
            self.write_queue_depth.put(tuple())

        self.write_queue.put(tuple())
        if self.display_frames:
            self.display_queue.put(tuple())

        logging.log(logging.INFO, f"Closing camera {self.camera_params['name']}")
        if cam is not None:
            cam.close()

        logging.debug(f"Acquisition run finished, {self.camera_params['name']}")


def end_processes(acquisition_loops, writers, disp, writer_timeout=60):
    # end acquisition loops
    for acquisition_loop in acquisition_loops:
        if acquisition_loop.is_alive():
            logging.log(
                logging.DEBUG,
                f"stopping acquisition loop ({acquisition_loop.camera_params['name']})",
            )
            # stop writinacquire_videog
            acquisition_loop.stop()
            # kill thread
            logging.log(
                logging.DEBUG,
                f"joining acquisition loop ({acquisition_loop.camera_params['name']})",
            )
            acquisition_loop.join(timeout=1)
            # kill if necessary
            if acquisition_loop.is_alive():
                # debug: notify user we had to terminate the acq loop
                logging.debug("Terminating acquisition loop (join timed out)")
                acquisition_loop.terminate()

    # end writers
    for writer in writers:
        if writer.is_alive():
            #     # wait to finish writing
            #     while writer.queue.qsize() > 0:
            #         print(writer.queue.qsize())
            #         time.sleep(0.1)
            writer.join(timeout=writer_timeout)

    # Debug: printer the writer's exitcode
    logging.debug(f"Writer exitcode: {writer.exitcode}")

    # end display
    if disp is not None:
        # TODO figure out why display.join hangs when there is >1 azure
        if disp.is_alive():
            disp.join(timeout=1)
        if disp.is_alive():
            disp.terminate()


def prepare_rec_dir(save_location, append_datetime=True):
    """Create a directory for saving the recording, optionally further 
    nested in a subdir named with the date and time.

    Parameters
    ----------
    save_location : str or Path
        The location to save the recording.
    """

    # Convert arg to Path, if necessary
    if not isinstance(save_location, Path):
        save_location = Path(save_location)

    # Resolve subfolder name, if requested
    if append_datetime:
        date_str = datetime.now().strftime("%y-%m-%d-%H-%M-%S-%f")
        save_location = save_location.joinpath(date_str)

    # Create the directory
    save_location.mkdir(parents=True, exist_ok=True)

    # Sanity check
    if not save_location.exists():
        raise ValueError(f"Failed to create save location {save_location}!")
    else:
        print(f'Created save location {save_location}')

    return save_location


def create_config_from_camera_list(camera_list, baseline_recording_config=None):
    """Create a recording config from a list of camera dicts.

    If baseline_recording_config is None, each camera's config will be 
    created from the default config for the brand. If baseline_recording_config
    is a dict containing a config for the cameras, it will be used as the
    starting point for each camera's config. 

    In either case, the default config is then overwritten with any 
    user-provided config values. 

    This process is repated for the Writer config for each camera.
    """

    # Create the recording config, from the baseline one if provided
    if baseline_recording_config is None:
        recording_config = {}
        recording_config["cameras"] = {}
        baseline_camera_names = []
    else:
        recording_config = baseline_recording_config.copy()
        baseline_camera_names = list(recording_config["cameras"].keys())

    # Copy the camera list so that we don't modify the original
    # as we pop stuff out of it
    user_camera_list = camera_list.copy()  
    user_camera_dict = {cam["name"]: cam for cam in user_camera_list}

    # Iterate over the union of camera names in the camera list plus 
    # camera names in the baseline recording config.
    user_camera_list_names = [cam.pop('name') for cam in user_camera_list]
    camera_names = set(user_camera_list_names + baseline_camera_names)

    for camera_name in camera_names:

        # If the camera is in the recording config but not the user camera list,
        # then we don't need to do anything, since the user didn't specify a config.
        if camera_name not in user_camera_list_names:
            continue

        # If the camera is in the user camera list but not the recording config,
        # then we need to create a new config for it. 
        # Otherwise, use what's already in the recording config as the starting point.
        this_user_cam_dict = user_camera_dict[camera_name]
        camera_brand = this_user_cam_dict.pop("brand")
        if camera_name not in recording_config["cameras"].keys():

            # Find the correct default camera and writer configs
            if camera_brand == "basler":
                cam_config = BaslerCamera.default_camera_config()
                writer_config = BaslerCamera.default_writer_config()
            elif camera_brand == "azure":
                cam_config = AzureCamera.default_config()
                writer_config = AzureCamera.default_writer_config()
            else:
                raise NotImplementedError

        elif camera_name in recording_config["cameras"].keys():
            cam_config = recording_config["cameras"][camera_name]
            writer_config = recording_config["cameras"][camera_name]["writer"]

        # Update the camera config with any user-provided config values
        for key in this_user_cam_dict.keys():
            if key in ALL_CAM_PARAMS:
                cam_config[key] = this_user_cam_dict.pop(key)

            if key in ALL_WRITER_PARAMS:
                writer_config[key] = this_user_cam_dict.pop(key)

            if key == "display":
                cam_config[key] = this_user_cam_dict.pop(key)

        # Save this writer config into this camera's config
        cam_config["writer"] = writer_config

        # Set display to false if not already specified
        if "display" not in cam_config:
            cam_config["display"] = False

        # Save this camera's config in the recording config
        recording_config["cameras"][camera_name] = cam_config

        # Ensure we've used all the params in the camera dict, 
        # if not the user is trying to pass some param that doesn't exist
        if len(this_user_cam_dict) > 0:
            raise ValueError(
                f"Unrecognized camera params: {this_user_cam_dict.keys()}. "
                "Did you misspell a param?"
            )

    return recording_config


def add_display_params_to_config(recording_config, display_params=None):
    """Add display params to a recording config.
    """
    if display_params is None:
        recording_config["rt_display_params"] = default_display_config()
    else: 
        recording_config["rt_display_params"] = display_params
    return recording_config


def load_config(config_filepath):
    """Load a recording config from a file.
    """
    with open(config_filepath, "r") as f:
        recording_config = yaml.load(f)
    return recording_config


def save_config(config_filepath, recording_config):
    """Save a recording config to a file.
    """
    with open(config_filepath, "w") as f:
        yaml.dump(recording_config, f)
    return


def validate_recording_config(recording_config, fps):
    """Validate a recording config dict.

    This function checks that the recording config dict is valid, 
    and raises an error if it is not.
    """

    # Ensure that the requested frame rate is a multiple of the azure's 30 fps rate
    if fps % 30 != 0:
        raise ValueError("Framerate must be a multiple of the Azure's frame rate (30)")

    # Ensure that the requested frame rate is a multiple of the display frame rate
    if fps % recording_config["rt_display_params"]["display_fps"] != 0:
        raise ValueError("Real-time framerate must be a factor of the capture frame rate")


def refactor_acquire_video(
        save_location, 
        camera_list, 
        fps=30, 
        recording_duration_s=60, 
        config_file=None,
        display_params=None, 
        append_datetime=True, 
        overwrite=False
):
    """
    """

    # Create the recording directory
    save_location = prepare_rec_dir(save_location, append_datetime=append_datetime)

    # Create a config file for the recording    
    if isinstance(config_file, str) or isinstance(config_file, Path):
        config = load_config(config_file)
    else:
        config = None
    config = create_config_from_camera_list(camera_list, config)  # Create a config file from the camera list + default camera configs
    config = add_display_params_to_config(config, display_params)  # Add display params to the config

    # TODO: add arduino configs

    # Check that the config is valid
    validate_recording_config(config, fps)

    # Save the config file before starting the recording
    config_filepath = save_location / "recording_config.yaml"
    save_config(config_filepath, config)

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
                    arduino, 
                    expected_confirmation="Waiting...", 
                    seconds_to_wait=2
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
            
            video_file = save_location / f"{name}.{serial_number}.avi"
            metadata_file = save_location / f"{name}.{serial_number}.metadata.csv"

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
                depth = True # uses 16 bit depth
            )
        else:
            
            video_file = save_location / f"{name}.{serial_number}.mp4"
            metadata_file = save_location / f"{name}.{serial_number}.metadata.csv"

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
            video_file_depth = save_location / f"{name}.{serial_number}.depth.avi"
            metadata_file = save_location / f"{name}.{serial_number}.metadata.depth.csv"
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
        acquisition_loop.ready.wait()  # blocks until the acq loop reports that it is ready
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
