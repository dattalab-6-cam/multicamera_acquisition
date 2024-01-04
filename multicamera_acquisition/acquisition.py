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
from multicamera_acquisition.paths import prepare_rec_dir, prepare_base_filename

# from multicamera_acquisition.interfaces.camera_azure import AzureCamera
from multicamera_acquisition.interfaces.arduino import (
    find_serial_ports, packIntAsLong, wait_for_serial_confirmation)
# from multicamera_acquisition.visualization import MultiDisplay


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
        # TODO: resolve device indices in one go before starting any cameras,
        # that way all six cameras don't have to iterate through all six of each other!
        # Then just add the device index to the config and allow the cameras to directly
        # receive a device index.
        cam = get_camera(
            brand=self.camera_config["brand"],
            id=self.camera_config["id"],
            name=self.camera_config["name"],
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

        current_iter = 0
        n_frames_received = 0
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
                    n_frames_received += 1

                    # If this is an azure camera, we write the depth data to a separate queue
                    if self.camera_config["brand"] == "azure":
                        depth, ir, camera_timestamp = data

                        self.write_queue.put(
                            tuple([ir, camera_timestamp, current_iter])
                        )
                        self.write_queue_depth.put(
                            tuple([depth, camera_timestamp, current_iter])
                        )
                        if self.acq_config["display_frames"]:
                            if current_iter % self.display_every_n == 0:
                                self.display_queue.put(
                                    tuple([depth, camera_timestamp, current_iter])
                                )
                    else:
                        data = data + tuple([current_iter])
                        self.write_queue.put(data)
                        if self.acq_config["display_frames"]:
                            if current_iter % self.acq_config["display_every_n"] == 0:
                                self.display_queue.put(data)

            except Exception as e:
                # if a frame was dropped, log the lost frame and contiue
                if type(e).__name__ == "SpinnakerException":
                    pass
                elif type(e).__name__ == "TimeoutException":
                    # print(f"{cam.name} cam:{e}")
                    print(f"Dropped frame on iter {current_iter} after receiving {n_frames_received} frames")
                    pass
                else:
                    raise e
                if self.acq_config["dropped_frame_warnings"]:
                    warnings.warn(
                        "Dropped {} frame on #{}: \n{}".format(
                            current_frame,
                            cam.serial_number,
                            type(e).__name__,  # , str(e)
                        )
                    )
            current_iter += 1
            if self.acq_config["max_frames_to_acqure"] is not None:
                if current_iter >= self.acq_config["max_frames_to_acqure"]:
                    break

        # Once the stop signal is received, stop the writer and dispaly processes
        print(f"Writing empties to stop queue, {self.camera_config['name']}")
        print(f"Received {n_frames_received} many frames over {current_iter} iterations, {self.camera_config['name']}")
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
        file_prefix=None,
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
        arduino:
            [list of arduino params]

    For example, here is a minimal config file for a single camera without an arduino:

        globals:
            fps: 30
        cameras:
            top:
                name: top
                brand: basler
                id: "12345678"  # ie the serial number, as a string
                gain: 6
                exposure_time: 1000
                display: True
                roi: null  # or an roi to crop the image
                trigger:
                    short_name: continuous  # convenience attr for no-trigger acquisition
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
    base_filename = prepare_base_filename(file_prefix=file_prefix, append_datetime=append_datetime, append_camera_serial=append_camera_serial)

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
        print(f"Using port {port} for arduino.")
    arduino = serial.Serial(port=port, timeout=1)  #TODO: un-hardcode the timeout

    # Delay recording to allow serial connection to connect
    sleep_duration = 2
    time.sleep(sleep_duration)

    # TODO: triggerdata file

    # Create the various processes
    writers = []
    acquisition_loops = []
    # display_queues = [] # TODO: implement display queues

    for camera_name, camera_dict in final_config["cameras"].items():

        # Create a writer queue
        write_queue = mp.Queue()

        # Generate file names
        if append_camera_serial:
            format_kwargs = dict(camera_name=camera_dict["name"], camera_id=camera_dict["id"])
        else:
            format_kwargs = dict(camera_name=camera_dict["name"])
        video_file_name = save_location / base_filename.format(**format_kwargs)
        metadata_file_name = save_location / base_filename.format(**format_kwargs).replace(".mp4", ".metadata.csv")

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

    # Tell the arduino to start recording by sending along the recording parameters
    fps = final_config["cameras"][camera_name]["fps"]
    inv_framerate = int(np.round(1e6 / fps, 0))
    num_cycles = int(recording_duration_s * 30)
    msg = b"".join(
        map(
            packIntAsLong,
            (
                num_cycles,
                inv_framerate,
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
        end_processes(acquisition_loops, writers, [])
        return save_location, video_file_name, final_config

    # Wait for the specified duration
    finished = False
    try:
        pbar = tqdm(total=recording_duration_s, desc="recording progress (s)")
        # how long to record
        datetime_prev = datetime.now()
        endtime = datetime_prev + timedelta(seconds=recording_duration_s + 10)
        while datetime.now() < endtime:

            # Check for the arduino to say we're done
            msg = arduino.readline().decode("utf-8").strip("\r\n")
            if len(msg) > 0:
                print(msg)
                # TODO: save trigger data
            if msg == "Finished":
                print("Finished recieved from arduino")
                finished = True
                break

            # Update pbar
            if (datetime.now() - datetime_prev).seconds > 0:
                pbar.update((datetime.now() - datetime_prev).seconds)
                datetime_prev = datetime.now()

        # If Python finishes first, wait a moment for the arduino to finish
        if not finished:
            try:
                confirmation = wait_for_serial_confirmation(
                    arduino, expected_confirmation="Finished", seconds_to_wait=10
                )
            except ValueError as e:
                print(e)

    except (KeyboardInterrupt) as e:
        pass

    finally:
        # End the processes and close the arduino regardless
        # of whether there was an error or not
        pbar.update((datetime.now() - datetime_prev).seconds)
        pbar.close()
        print("Ending processes, this may take a moment...")
        arduino.close()
        end_processes(acquisition_loops, writers, None, writer_timeout=300)
        print("Done.")

    return save_location, video_file_name, final_config
