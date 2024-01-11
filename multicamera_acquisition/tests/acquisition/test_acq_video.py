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

from multicamera_acquisition.video_utils import (
    count_frames,
)

from multicamera_acquisition.writer import (
    FFMPEG_Writer,
    NVC_Writer,
)

from multicamera_acquisition.tests.writer.test_writers import (
    fps,
    n_test_frames,
)

from multicamera_acquisition.tests.interfaces.test_ir_cameras import ( 
    camera_type,
    camera_brand
)

from multicamera_acquisition.visualization import MultiDisplay


@pytest.fixture(scope="session")
def trigger_type(pytestconfig):
    return pytestconfig.getoption("trigger_type")  # default no_trigger (ie no trigger required), see conftest.py


@pytest.fixture(scope="session")
def writer_type(pytestconfig):
    return pytestconfig.getoption("writer_type")  # default nvc, see conftest.py


def test_refactor_acquire_video(tmp_path, camera_brand, n_test_frames, trigger_type, writer_type, fps):

    camera_list = [
        {"name": "top", "brand": camera_brand, "id": 0},
        {"name": "bottom", "brand": camera_brand, "id": 1}
    ]

    # Set the trigger behavior
    for camera in camera_list:
        camera["trigger_type"] = trigger_type

    # Parse the "camera list" into a partial config
    partial_new_config = partial_config_from_camera_list(camera_list)

    # Add writer configs to each camera config
    if writer_type == "nvc":
        try:
            import PyNvCodec as nvc
        except ImportError:
            pytest.skip("PyNvCodec not installed, skipping muxing test")
        writer_config = NVC_Writer.default_writer_config(fps).copy()
    elif writer_type == "ffmpeg":
        writer_config = FFMPEG_Writer.default_writer_config(fps).copy()

    for camera_name in partial_new_config["cameras"].keys():
        writer_config["camera_name"] = camera_name
        partial_new_config["cameras"][camera_name]["writer"] = writer_config

    # Create the full config, filling in defaults where necessary
    full_config = create_full_camera_default_config(partial_new_config, fps)
    full_config["globals"] = {}
    full_config["globals"]["fps"] = fps
    full_config["globals"]["arduino_required"] = (trigger_type == "arduino")

    # Set up the acquisition loop part of the config
    acq_config = AcquisitionLoop.default_acq_loop_config().copy()
    acq_config["max_frames_to_acqure"] = n_test_frames
    full_config["acq_loop"] = acq_config

    # Run the func!
    save_loc, first_video_file_name, full_config = refactor_acquire_video(
        tmp_path,
        full_config,
        recording_duration_s=int(n_test_frames / fps),
        append_datetime=True,
        overwrite=False,
    )

    # Check that the video exists
    for camera_name in full_config["cameras"].keys():
        assert os.path.exists(first_video_file_name)
        assert os.path.exists(str(first_video_file_name).replace(".mp4", ".metadata.csv"))

    # Check that the video has the right number of frames
    for camera_name in full_config["cameras"].keys():
        assert count_frames(str(first_video_file_name)) == n_test_frames


def test_refactor_acquire_video_multiple_vids_muxing(tmp_path, camera_brand, n_test_frames, trigger_type, fps):

    try:
        import PyNvCodec as nvc
    except ImportError:
        pytest.skip("PyNvCodec not installed, skipping muxing test")

    camera_list = [
        {"name": "top", "brand": camera_brand, "id": 0},
        {"name": "bottom", "brand": camera_brand, "id": 1}
    ]

    # Set the trigger behavior
    for camera in camera_list:
        camera["trigger_type"] = trigger_type

    # Parse the "camera list" into a partial config
    partial_new_config = partial_config_from_camera_list(camera_list)

    # Add NVC writers to each camera
    nvc_writer_config = NVC_Writer.default_writer_config(fps).copy()
    nvc_writer_config["auto_remux_videos"] = True  # this is the default, but just to make it explicit / in case we change the default

    # KEY LINE FOR THIS TEST
    assert n_test_frames % 2 == 0
    nvc_writer_config["max_video_frames"] = int(n_test_frames / 2)

    for camera_name in partial_new_config["cameras"].keys():
        nvc_writer_config["camera_name"] = camera_name
        partial_new_config["cameras"][camera_name]["writer"] = nvc_writer_config

    # Create the full config, filling in defaults where necessary
    full_config = create_full_camera_default_config(partial_new_config, fps)
    full_config["globals"] = {}
    full_config["globals"]["fps"] = fps
    full_config["globals"]["arduino_required"] = (trigger_type == "arduino")

    # Set up the acquisition loop part of the config
    acq_config = AcquisitionLoop.default_acq_loop_config().copy()
    acq_config["max_frames_to_acqure"] = n_test_frames
    full_config["acq_loop"] = acq_config

    # Run the func!
    save_loc, first_video_file_name, full_config = refactor_acquire_video(
        tmp_path,
        full_config,
        recording_duration_s=(n_test_frames / fps),
        append_datetime=True,
        overwrite=False,
    )

    # Check that the videos exist
    for camera_name in full_config["cameras"].keys():

        # Check that the first video exists
        assert os.path.exists(first_video_file_name)
        assert os.path.exists(str(first_video_file_name).replace(".mp4", ".metadata.csv"))

        # Check that the next video exists
        next_video_file_name = str(first_video_file_name).replace(".0", f".{nvc_writer_config['max_video_frames']}")
        assert os.path.exists(next_video_file_name)
        assert os.path.exists(str(next_video_file_name).replace(".mp4", ".metadata.csv"))

    # Check that the video has the right number of frames
    # NB: this won't work unless we mux the videos, so this also tests the muxing.
    for camera_name in full_config["cameras"].keys():
        assert count_frames(str(first_video_file_name)) == n_test_frames / 2
        assert count_frames(str(next_video_file_name)) == n_test_frames / 2


def test_refactor_acquire_video_muxing(tmp_path, camera_brand, n_test_frames, trigger_type, fps):

    try:
        import PyNvCodec as nvc
    except ImportError:
        pytest.skip("PyNvCodec not installed, skipping muxing test")

    camera_list = [
        {"name": "top", "brand": camera_brand, "id": 0},
        {"name": "bottom", "brand": camera_brand, "id": 1}
    ]

    # Set the trigger behavior
    for camera in camera_list:
        camera["trigger_type"] = trigger_type

    # Parse the "camera list" into a partial config
    partial_new_config = partial_config_from_camera_list(camera_list)

    # Add NVC writers to each camera
    nvc_writer_config = NVC_Writer.default_writer_config(fps).copy()
    nvc_writer_config["auto_remux_videos"] = True  # this is the default, but just to make it explicit / in case we change the default
    for camera_name in partial_new_config["cameras"].keys():
        nvc_writer_config["camera_name"] = camera_name
        partial_new_config["cameras"][camera_name]["writer"] = nvc_writer_config

    # Create the full config, filling in defaults where necessary
    full_config = create_full_camera_default_config(partial_new_config, fps)
    full_config["globals"] = {}
    full_config["globals"]["fps"] = fps
    full_config["globals"]["arduino_required"] = (trigger_type == "arduino")

    # Set up the acquisition loop part of the config
    acq_config = AcquisitionLoop.default_acq_loop_config().copy()
    acq_config["max_frames_to_acqure"] = n_test_frames
    full_config["acq_loop"] = acq_config

    display_config = MultiDisplay.default_MultiDisplay_config().copy()
    full_config["rt_display"] = display_config

    # Run the func!
    save_loc, first_video_file_name, full_config = refactor_acquire_video(
        tmp_path,
        full_config,
        recording_duration_s=int(n_test_frames / fps),
        append_datetime=True,
        overwrite=False,
    )

    # Check that the video exists
    for camera_name in full_config["cameras"].keys():
        assert os.path.exists(first_video_file_name)
        assert os.path.exists(str(first_video_file_name).replace(".mp4", ".metadata.csv"))

    # Check that the video has the right number of frames
    # NB: this won't work unless we mux the videos, so this also tests the muxing.
    for camera_name in full_config["cameras"].keys():
        assert count_frames(str(first_video_file_name)) == n_test_frames
