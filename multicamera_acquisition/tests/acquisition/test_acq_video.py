import pytest
import os

from multicamera_acquisition.acquisition import (
    refactor_acquire_video,
    AcquisitionLoop
)

from multicamera_acquisition.interfaces.config import (
    partial_config_from_camera_list,
    create_full_camera_default_config,
)

from multicamera_acquisition.video_io_ffmpeg import (
    count_frames,
)

from multicamera_acquisition.writer import (
    FFMPEG_Writer,
)

from multicamera_acquisition.tests.writer.test_writers import (
    fps,
    n_test_frames,
)

from multicamera_acquisition.tests.interfaces.test_ir_cameras import ( 
    camera_type,
    camera_brand
)


def test_refactor_acquire_video(tmp_path, camera_brand, n_test_frames):
    camera_list = [
        {"name": "top", "brand": camera_brand, "id": 0, "short_name": "continuous"},
        {"name": "bottom", "brand": camera_brand, "id": 1, "short_name": "continuous"}
    ]

    fps = 30

    # Parse the "camera list" into a partial config
    partial_new_config = partial_config_from_camera_list(camera_list, fps)

    # Add ffmpeg writers to each camera
    # TODO: allow this to be nvc dynamically for testing. 
    ffmpeg_writer_config = FFMPEG_Writer.default_writer_config(fps)
    for camera_name in partial_new_config["cameras"].keys():
        ffmpeg_writer_config["camera_name"] = camera_name
        partial_new_config["cameras"][camera_name]["writer"] = ffmpeg_writer_config

    # Create the full config, filling in defaults where necessary
    full_config = create_full_camera_default_config(partial_new_config)

    # Set up the acquisition loop part of the config
    acq_config = AcquisitionLoop.default_acq_loop_config()
    acq_config["max_frames_to_acqure"] = n_test_frames
    full_config["acq_loop"] = acq_config

    # Run the func!
    save_loc, full_config = refactor_acquire_video(
        tmp_path,
        full_config,
        recording_duration_s=5,
        append_datetime=True,
        overwrite=False,
    )

    # Check that the video exists
    for camera_name in full_config["cameras"].keys():
        assert os.path.exists(save_loc / f"{camera_name}.mp4")
        assert os.path.exists(save_loc / f"{camera_name}.metadata.csv")

    # Check that the video has the right number of frames
    for camera_name in full_config["cameras"].keys():
        assert count_frames(str(save_loc / f"{camera_name}.mp4")) == n_test_frames
