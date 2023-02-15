from multicamera_acquisition.interfaces import get_camera
from multicamera_acquisition.video_io import write_frame
from multicamera_acquisition.paths import ensure_dir
from multicamera_acquisition.interfaces.arduino import (
    packIntAsLong,
    wait_for_serial_confirmation,
)
from multicamera_acquisition.visualization import Display, MultiDisplay

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

import serial
from pathlib2 import Path
from multicamera_acquisition.video_io import count_frames


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

    def stop(self):
        self.stopped.set()

    def prime(self):
        self.ready.clear()
        self.primed.set()

    def run(self):

        cam = get_camera(brand=self.brand, **self.camera_params)

        self.ready.set()
        self.primed.wait()

        cam.start()
        self.ready.set()

        current_frame = 0
        while not self.stopped.is_set():
            try:
                data = cam.get_array(timeout=self.frame_timeout, get_timestamp=True)
                if len(data) != 0:
                    data = data + tuple([current_frame])
                self.write_queue.put(data)
                if self.display_frames:
                    if current_frame % self.display_frequency == 0:
                        self.display_queue.put(data)
            except Exception as e:
                # if a frame was dropped, log the lost frame and contiue
                if type(e).__name__ == "SpinnakerException":
                    pass
                elif type(e).__name__ == "TimeoutException":
                    pass
                else:
                    raise e
                if self.dropped_frame_warnings:
                    warnings.warn(
                        "Dropped {} frame on #{}: \n{}".format(
                            current_frame, cam.serial_number, type(e).__name__  # , str(e)
                        )
                    )
            current_frame += 1

        self.write_queue.put(tuple())
        if self.display_frames:
            self.display_queue.put(tuple())

        if cam is not None:
            cam.close()


class Writer(mp.Process):
    def __init__(
        self,
        queue,
        video_file_name,
        metadata_file_name,
        camera_serial,
        camera_name,
        ffmpeg_options,
    ):
        super().__init__()
        self.pipe = None
        self.queue = queue
        self.video_file_name = video_file_name
        self.ffmpeg_options = ffmpeg_options
        self.metadata_file_name = metadata_file_name
        self.camera_name = camera_name
        self.camera_serial = camera_serial

        with open(self.metadata_file_name, "w") as metadata_f:
            metadata_writer = csv.writer(metadata_f)
            metadata_writer.writerow(["frame_id", "frame_timestamp", "frame_image_uid","queue_size"])

    def run(self):
        frame_id = 0
        with open(self.metadata_file_name, "a") as metadata_f:
            metadata_writer = csv.writer(metadata_f)
            while True:
                data = self.queue.get()
                if len(data) == 0:
                    break
                else:
                    # get the computer datetime of the frame
                    frame_image_uid = str(round(time.time(), 5)).zfill(5)
                    img, camera_timestamp, current_frame = data
                    qsize = self.queue.qsize()
                    # if the frame is corrupted
                    if img is None:
                        continue
                    metadata_writer.writerow(
                        [
                            current_frame,
                            camera_timestamp,
                            frame_image_uid,
                            str(qsize)
                        ]
                    )
                    self.append(img)
            self.close()

    def append(self, data):
        self.pipe = write_frame(
            self.video_file_name, data, pipe=self.pipe, **self.ffmpeg_options
        )

    def close(self):
        if self.pipe is not None:
            self.pipe.stdin.close()

def end_processes(acquisition_loops, writers, disp):

    # end acquisition loops
    for acquisition_loop in acquisition_loops:
        acquisition_loop.stop()
        acquisition_loop.join()

    # end writers
    for writer in writers:
        writer.join()

    # end display
    if disp is not None:
        disp.join()


def acquire_video(
    save_location,
    camera_list,
    recording_duration_s,
    framerate=30,
    display_framerate=30,
    serial_timeout_duration_s=0.1,
    display_downsample=4,
    overwrite=False,
    append_datetime=True,
    verbose=True,
    n_input_trigger_states=4,
    ffmpeg_options={},
    arduino_args=[],
):

    if verbose:
        logging.log(logging.INFO, "Checking cameras...")

    camera_brands = np.array([i["brand"] for i in camera_list])
    # if there are cameras that are not flir or basler, raise an error
    for i in camera_brands:
        if i not in ["flir", "basler"]:
            raise ValueError(
                "Camera brand must be either 'flir' or 'basler', not {}".format(i)
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
    ensure_dir(save_location)

    triggerdata_file = save_location / "triggerdata.csv"
    if triggerdata_file.exists() and (overwrite == False):
        raise FileExistsError(f"CSV file {triggerdata_file} already exists")

    if verbose:
        logging.log(logging.INFO, "Initializing cameras...")
    # initialize cameras
    writers = []
    acquisition_loops = []
    display_queues = []
    camera_names = []

    # create acquisition loops
    for camera_dict in camera_list:
        name = camera_dict["name"]
        serial_number = camera_dict["serial"]

        ffmpeg_options = {}
        for key in ['gpu','quality']:
            if key in camera_dict:
                ffmpeg_options[key] = camera_dict[key]

        if "display" in camera_dict.keys():
            display_frames = camera_dict["display"]
        else:
            display_frames = False

        if verbose:
            logging.log(logging.INFO, f"Camera {name}...")

        video_file = save_location / f"{name}.{serial_number}.avi"
        metadata_file = save_location / f"{name}.{serial_number}.metadata.csv"

        if video_file.exists() and (overwrite == False):
            raise FileExistsError(f"Video file {video_file} already exists")

        # create a writer queue
        write_queue = mp.Queue()
        writer = Writer(
            write_queue,
            video_file,
            metadata_file,
            serial_number,
            name,
            ffmpeg_options,
            )

        display_queue = None
        if display_frames:
            # create a writer queue
            display_queue = mp.Queue()
            camera_names.append(name)
            display_queues.append(display_queue)

        # prepare the acuqisition loop in a separate thread
        acquisition_loop = AcquisitionLoop(
            write_queue=write_queue,
            display_queue=display_queue,
            display_frames=display_frames,
            display_frequency=display_frequency,
            **camera_dict
        )

        # initialize acquisition
        writer.start()
        writers.append(writer)

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
        )
        disp.start()
    else:
        disp=None

    if verbose:
        logging.log(logging.INFO, f"Preparing acquisition loops")

    # prepare acquisition loops
    for acquisition_loop in acquisition_loops:
        acquisition_loop.prime()
        acquisition_loop.ready.wait()

    if verbose:
        logging.log(logging.INFO, f"Initializing Arduino...")

    # prepare communication with arduino
    serial_ports = glob.glob("/dev/ttyACM*")
    # check that there is an arduino available
    if len(serial_ports) == 0:
        raise ValueError("No serial device (i.e. Arduino) available to capture frames")
    port = glob.glob("/dev/ttyACM*")[0]
    arduino = serial.Serial(port=port, timeout=serial_timeout_duration_s)

    # delay recording to allow serial connection to connect
    time.sleep(1.0)

    # create a triggerdata file
    with open(triggerdata_file, "w") as triggerdata_f:
        triggerdata_writer = csv.writer(triggerdata_f)
        triggerdata_writer.writerow(
            ["pulse_id", "arduino_ms"]
            + [f"flag_{i}" for i in range(n_input_trigger_states)]
        )

    # Tell the arduino to start recording by sending along the recording parameters
    inv_framerate = int(1e6 / framerate)
    num_cycles = int(recording_duration_s * framerate)
    msg = b"".join(
        map(
            packIntAsLong,
            (
                num_cycles,
                inv_framerate,
                *arduino_args,
            ),
        )
    )
    arduino.write(msg)

    if verbose:
        logging.log(logging.INFO, f"Starting Acquisition...")

    # Run acquision
    try: confirmation = wait_for_serial_confirmation(arduino, "Start")
    except: end_processes(acquisition_loops, writers, disp)

    # how long to record
    datetime_prev = datetime.now()
    endtime = datetime_prev + timedelta(seconds=recording_duration_s + 10)

    # while current time is less than initial time + recording_duration_s
    pbar = tqdm(total=recording_duration_s, desc="recording progress (s)")
    while datetime.now() < endtime:
        confirmation = arduino.readline().decode("utf-8").strip("\r\n")
        if (datetime.now() - datetime_prev).seconds > 0:
            pbar.update((datetime.now() - datetime_prev).seconds)
            datetime_prev = datetime.now()
        # save input data flags
        if len(confirmation) > 0:
            print(confirmation)
            if confirmation[:7] == "input: ":
                with open(triggerdata_file, "a") as triggerdata_f:
                    triggerdata_writer = csv.writer(triggerdata_f)
                    states = confirmation[7:].split(",")[:-2]
                    frame_num = confirmation[7:].split(",")[-2]
                    arduino_clock = confirmation[7:].split(",")[-1]
                    triggerdata_writer.writerow([frame_num, arduino_clock] + states)
            if verbose:
                print(confirmation)

        if confirmation == "Finished":
            print("End Acquisition")
            break

    pbar.close()

    if confirmation != "Finished":
        confirmation = wait_for_serial_confirmation(arduino, "Finished")

    if verbose:
        logging.log(logging.INFO, f"Closing")

    end_processes(acquisition_loops, writers, disp)


    if verbose:
        # count each frame
        for camera_dict in camera_list:
            name = camera_dict["name"]
            serial_number = camera_dict["serial"]
            video_file = save_location / f"{name}.{serial_number}.avi"
            print(f"Frames ({name}):", count_frames(video_file.as_posix()))

    return save_location
