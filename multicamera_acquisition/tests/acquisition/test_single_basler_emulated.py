import unittest
import os
import sys
from pathlib import Path
import logging

num_devices = 1
os.environ["PYLON_CAMEMU"] = f"{num_devices}"
from pypylon import pylon
import multiprocessing as mp
from datetime import datetime, timedelta

from multicamera_acquisition.tests.interfaces.test_camera_basler import PylonEmuTestCase
from multicamera_acquisition.acquisition import AcquisitionLoop, end_processes, Writer
from multicamera_acquisition.paths import ensure_dir

class TestBaslerEmulated():

    def test_acquire_no_arduino(self):
        """Test acquiring images without an arduino"""
        
        # Set up a logger
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)

        # Parameters for an emulated basler
        camera_dict = {
            "brand": "basler_emulated",
            "gain": 0,
            "exposure_time": 1000,
            "trigger": "software",
            "frame_timeout": 1000,
            "roi": None,
            "readout_mode": "SensorReadoutMode_Normal",
        }
        ffmpeg_options = {"fps": 90}

        # We'll save a test video
        ensure_dir("test_vids")

        # Remove anything already in the test dir
        for f in Path("./test_vids").glob("*"):
            os.remove(f)

        # Set up the writer
        write_queue = mp.Queue()
        writer = Writer(
            queue=write_queue,
            video_file_name=Path("./test_vids/test_vid.mp4"),
            metadata_file_name=Path("./test_vids/metadata.csv"),
            camera_serial="emulated",
            fps=90,
            camera_name="emulated",
            camera_brand=camera_dict["brand"],
            ffmpeg_options=ffmpeg_options
        )

        # Set up the emulated camera
        acquisition_loop = AcquisitionLoop(
            write_queue=write_queue,
            display_queue=None,
            **camera_dict,
        )

        # Start the acquisition
        logging.info("Starting acquisition...")
        writer.start()
        acquisition_loop.start()

        # Wait for a few seconds while it goes
        recording_duration_s = 2
        datetime_prev = datetime.now()
        endtime = datetime_prev + timedelta(seconds=recording_duration_s + 0.5)
        logging.info("Waiting for two seconds to go by...")
        while datetime.now() < endtime:
            pass
        logging.info("Time elapsed!")
        
        # End the acquisition loop
        end_processes([acquisition_loop], [writer], None, writer_timeout=3)
        logging.info("Processes ended.")

        # TODO - pytest says this passes, but the process doesn't fully return
        # and so there's no video actualyl written, and pytest never closes.