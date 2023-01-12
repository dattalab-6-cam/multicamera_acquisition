from multicamera_acquisition.interfaces import get_camera
from multicamera_acquisition.videowriter import write_frames
from multicamera_acquisition.paths import ensure_dir
from multicamera_acquisition.interfaces.arduino import (
    packIntAsLong,
    wait_for_serial_confirmation,
)

import multiprocessing as mp
import csv
import warnings
import time
import csv
from datetime import datetime, timedelta
import glob
import logging
from tqdm import tqdm

import serial
from pathlib2 import Path
from multicamera_acquisition.videowriter import count_frames


class AcquisitionLoop(mp.Process):
    """A process that acquires images from a camera and writes them to a queue."""

    def __init__(self, write_queue, brand="flir", frame_timeout=1000, **camera_params):
        super().__init__()

        self.ready = mp.Event()
        self.primed = mp.Event()
        self.stopped = mp.Event()
        self.write_queue = write_queue
        self.camera_params = camera_params
        self.brand = brand
        self.frame_timeout = frame_timeout

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
            except Exception as e:
                # if a frame was dropped, log the lost frame and contiue
                if type(e).__name__ == "SpinnakerException":
                    pass
                elif type(e).__name__ == "TimeoutException":
                    pass
                else:
                    raise e
                warnings.warn(
                    "Dropped {} frame on #{}: \n{}:{}".format(
                        current_frame, cam.serial_number, type(e).__name__, str(e)
                    )
                )
            current_frame += 1

        self.write_queue.put(tuple())
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
        **ffmpeg_options,
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
            metadata_writer.writerow(["frame_id", "frame_timestamp", "frame_image_uid"])

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
                    # if the frame is corrupted
                    if img is None:
                        continue
                    metadata_writer.writerow(
                        [
                            current_frame,
                            camera_timestamp,
                            frame_image_uid,
                        ]
                    )
                    self.append(img)
            self.close()

    def append(self, data):
        self.pipe = write_frames(
            self.video_file_name, data[None], pipe=self.pipe, **self.ffmpeg_options
        )

    def close(self):
        if self.pipe is not None:
            self.pipe.stdin.close()


def acquire_video(
    save_location,
    camera_list,
    recording_duration_s,
    brand="flir",
    framerate=30,
    exposure_time=2000,
    serial_timeout_duration_s=0.1,
    overwrite=False,
    append_datetime=True,
    verbose=True,
    n_input_trigger_states=4,
):

    if brand not in ["flir", "basler"]:
        raise NotImplementedError

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

    # initialize cameras
    writers = []
    acquisition_loops = []

    # create acquisition loops
    for camera_dict in camera_list:
        name = camera_dict["name"]
        serial_number = camera_dict["serial"]

        video_file = save_location / f"{name}.{serial_number}.avi"
        metadata_file = save_location / f"{name}.{serial_number}.triggerdata.csv"

        if video_file.exists() and (overwrite == False):
            raise FileExistsError(f"Video file {video_file} already exists")

        # create a writer queue
        write_queue = mp.Queue()
        writer = Writer(
            write_queue,
            video_file_name=video_file,
            metadata_file_name=metadata_file,
            fps=framerate,
            camera_serial=serial_number,
            camera_name=name,
        )

        # prepare the acuqisition loop in a separate thread
        acquisition_loop = AcquisitionLoop(
            write_queue,
            brand=brand,
            serial_number=serial_number,
            exposure_time=exposure_time,
            gain=12,
        )

        # initialize acquisition
        writer.start()
        writers.append(writer)
        acquisition_loop.start()
        acquisition_loop.ready.wait()
        acquisition_loops.append(acquisition_loop)
        if verbose:
            logging.info(f"Initialized {name} ({serial_number})")

    # prepare acquisition loops
    for acquisition_loop in acquisition_loops:
        acquisition_loop.prime()
        acquisition_loop.ready.wait()

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
    num_cycles = int(recording_duration_s * framerate / 2)
    msg = b"".join(
        map(
            packIntAsLong,
            (
                num_cycles,
                exposure_time,
                inv_framerate,
            ),
        )
    )
    arduino.write(msg)

    # Run acquision
    confirmation = wait_for_serial_confirmation(arduino, "Start")
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

    # end acquisition loops
    for acquisition_loop in acquisition_loops:
        acquisition_loop.stop()
        acquisition_loop.join()

    # @CALEB: what is the purpose of this?
    for writer in writers:
        writer.join()

    if verbose:
        # count each frame
        for camera_dict in camera_list:
            name = camera_dict["name"]
            serial_number = camera_dict["serial"]
            video_file = save_location / f"{name}.{serial_number}.avi"
            print(f"Frames ({name}):", count_frames(video_file.as_posix()))
