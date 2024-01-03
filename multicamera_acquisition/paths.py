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
    if type(file_path) == str:
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
    elif type(file_path) == pathlib2.PosixPath:
        # if this is a file
        if len(file_path.suffix) > 0:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        else:
            file_path.mkdir(parents=True, exist_ok=True)


def most_recent_subdirectory(dataset_loc):
    """return the subdirectory that has been generated most
    recently with the "%Y-%m-%d_%H-%M-%S" time scheme used in AVGN
    """
    if not isinstance(dataset_loc, Path):
        dataset_loc = Path(dataset_loc)
    subdir_list = list((dataset_loc).iterdir())
    directory_dates = [
        datetime.strptime(i.name, "%Y-%m-%d_%H-%M-%S") for i in subdir_list
    ]
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
        date_str = datetime.now().strftime("%y-%m-%d-%H-%M-%S-%f")
        save_location = save_location.joinpath(date_str)

    # Check if the directory already exists
    if save_location.exists() and not overwrite:
        raise ValueError(f"Save location {save_location} already exists, if you want to overwrite set overwrite to True!")
    elif save_location.exists() and overwrite and not append_datetime:
        print(f"Files in save location {save_location} will be overwritten, are you sure?")
        input("Press Enter to continue...")
        shutil.rmtree(save_location)

    # Create the directory
    save_location.mkdir(parents=True, exist_ok=True)

    # Sanity check
    if not save_location.exists():
        raise ValueError(f"Failed to create save location {save_location}!")
    else:
        print(f'Created save location {save_location}')

    return save_location
