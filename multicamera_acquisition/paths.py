from pathlib2 import Path
import pathlib2
import os
from datetime import datetime
import numpy as np
import shutil

PROJECT_DIR = Path(__file__).resolve().parents[1]
PACKAGE_DIR = Path(__file__).resolve().parent
DATA_DIR = PROJECT_DIR / "data"


def ensure_dir(file_path):
    """create a safely nested folder"""
    if isinstance(file_path, str):
        if "." in os.path.basename(os.path.normpath(file_path)):
            directory = os.path.dirname(file_path)
        else:
            directory = os.path.normpath(file_path)
        if not os.path.exists(directory):
            try:
                os.makedirs(directory)
            except FileExistsError as e:
                # multiprocessing can cause directory creation problems
                print(e)
    elif isinstance(file_path, pathlib2.PosixPath):
        # if this is a file
        if len(file_path.suffix) > 0:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            file_path.mkdir(parents=True, exist_ok=True)


def most_recent_subdirectory(dataset_loc):
    """return the subdirectory that has been generated most
    recently with the "%Y%m%d-%H%M%S" time scheme used in AVGN
    """
    if not isinstance(dataset_loc, Path):
        dataset_loc = Path(dataset_loc)
    subdir_list = list((dataset_loc).iterdir())
    directory_dates = [datetime.strptime(i.name, "%Y%m%d_%H%M%S") for i in subdir_list]
    return subdir_list[np.argsort(directory_dates)[-1]]


def prepare_rec_dir(save_location, append_datetime=True, overwrite=False):
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
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_location = save_location.joinpath(date_str)

    # Check if the directory already exists
    if save_location.exists() and not overwrite:
        raise ValueError(
            f"Save location {save_location} already exists, if you want to overwrite set overwrite to True!"
        )
    elif save_location.exists() and overwrite and not append_datetime:
        print(
            f"Files in save location {save_location} will be overwritten, are you sure?"
        )
        input("Press Enter to continue...")
        shutil.rmtree(save_location)

    # Create the directory
    save_location.mkdir(parents=True, exist_ok=True)

    # Sanity check
    if not save_location.exists():
        raise ValueError(f"Failed to create save location {save_location}!")
    else:
        print(f"Created save location {save_location}")

    return save_location


def prepare_base_filename(
    file_prefix=None, append_datetime=True, append_camera_serial=False
):
    """
    The default file name is save_location / {timestamp}.{camera_name}.{first_frame_number}.mp4,
    where timestamp is formatted like 20240103_135203 (“%Y%m%d_%H%M%S”), and first_frame_number is 0 for the first video
    and (max_frames_per_vid *i) for each subsequent i-th video.

    The timestamped directories are formatted the same.

    -- It is possible to have no timestamp
    -- It is possible to include a custom prefix
    The order of precedence is: prefix.timestamp.camera_name.serial_number.first_frame_num.mp4

    Multiple files from the same recording are initially saved into the same save_location, with separate videos + metadata + triggerdata.
    The timestamp for each new file is still the same as the first video.
    It is then up to the user if they want to create further nested directory structure for processing where each file set (video / metadata file / etc) is in its own subdir.
    """

    now = datetime.now().strftime("%Y%m%d_%H%M%S")

    base_filename = "{camera_name}.0.mp4"

    if append_datetime:
        base_filename = now + "." + base_filename

    if file_prefix is not None:
        base_filename = file_prefix + "." + base_filename

    if append_camera_serial:
        base_filename = base_filename.replace(".0.mp4", ".{camera_id}.0.mp4")

    return base_filename
