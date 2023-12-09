from multicamera_acquisition.interfaces import get_camera
from multicamera_acquisition.video_io_ffmpeg import write_frame
from multicamera_acquisition.paths import ensure_dir
from multicamera_acquisition.interfaces.arduino import (
    packIntAsLong,
    wait_for_serial_confirmation,
    find_serial_ports,
)
from multicamera_acquisition.visualization import MultiDisplay
from multicamera_acquisition.writer import Writer

import multiprocessing as mp
import csv
import warnings
import time
import csv
from datetime import datetime, timedelta
import glob
import logging
from tqdm import tqdm
import numpy as np
import sys

import serial
from pathlib import Path
from multicamera_acquisition.video_io_ffmpeg import count_frames


class AcquisitionLoop(mp.Process):
    """A process that acquires images from a camera and writes them to a queue."""

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
        # get the camera if it hasn't been passed in (e.g. for azure)
        if self.cam is None:
            cam = get_camera(brand=self.brand, **self.camera_params)
        else:
            cam = self.cam
        self.ready.set()
        self.primed.wait()

        # tell the camera to start grabbing
        cam.start()
        # once the camera is started grabbing, allow the main
        # process to continue
        self.ready.set()

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


def end_processes(acquisition_loops, writers, disp):
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
                acquisition_loop.terminate()

    # end writers
    for writer in writers:
        if writer.is_alive():
            #     # wait to finish writing
            #     while writer.queue.qsize() > 0:
            #         print(writer.queue.qsize())
            #         time.sleep(0.1)
            writer.join(timeout=60)

    # end display
    if disp is not None:
        # TODO figure out why display.join hangs when there is >1 azure
        if disp.is_alive():
            disp.join(timeout=1)
        if disp.is_alive():
            disp.terminate()


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
    if not all(exp <= 1000 for exp in exp_times):
        raise ValueError("Max exposure time is 1000 microseconds")

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
    print(f'Save location exists: {save_location.exists()}')
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
        acquisition_loop.ready.wait()
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
            logging.log(logging.LOG, "Waiting for finished confirmation")
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
    except KeyboardInterrupt as e:
        pass

    end_processes(acquisition_loops, writers, disp)

    pbar.close()

    return save_location, camera_list
