import numpy as np
from multicamera_acquisition.config import load_config
from multicamera_acquisition.interfaces.microcontroller import Microcontroller


def estimate_frame_indexes(timestamps):
    """
    Estimate the frame indexes from a sequence of timestamps (useful to detecting
    dropped frames). This function assumes that the first frame corresponds to index 0,
    i.e. the first frame was not dropped.

    Parameters
    ----------
    timestamps : np.ndarray
        Array of timestamps (in microseconds) for each frame in the video.

    Returns
    -------
    frame_indexes : np.ndarray
        Array of indices of captured frames.

    dropped_frames : np.ndarray
        Array of indices of dropped frames.


    Examples
    --------
    >>> timestamps = np.array([0, 33333, 66666, 133333, 166666])
    >>> detect_dropped_frames(timestamps)
    (array([3]), array([0, 1, 2, 4, 5]))
    """
    # Estimate number of periods between frames
    time_diffs = np.diff(timestamps)
    quantized_diffs = np.rint(time_diffs / np.median(time_diffs))

    # Estimate frame indexes
    frame_indexes = np.cumsum(quantized_diffs).astype(int)
    frame_indexes = np.insert(frame_indexes, 0, 0)

    # Estimate dropped frames
    dropped_frames = np.setdiff1d(np.arange(frame_indexes.max() + 1), frame_indexes)
    return frame_indexes, dropped_frames


def get_trigger_times(
    config_path, camera_category, num_triggers=None, recording_duration_s=None
):
    """
    Reconstruct the times (in microseconds) that the microcontroller triggered a camera.

    Parameters
    ----------
    config_path : str
        Path to the configuration file for a recording session.

    camera_category : str
        Category of the camera for which to reconstruct trigger times. Must be one of:
        ["top_basler", "bottom_basler", "azure"]. If a single camera was used, the
        category should be "top_basler".

    num_triggers : int, optional
        Number of triggers to reconstruct. Required if `recording_duration_s` is None.

    recording_duration_s : float, optional
        Duration of the recording session in seconds. Required if `num_triggers` is None.

    Returns
    -------
    trigger_times : np.ndarray
        Array of trigger times (in microseconds) for the camera.
    """
    trigger_info = Microcontroller(
        config=load_config(config_path), suppress_side_effects=True
    ).trigger_info

    cycle_duration = trigger_info["cycle_duration"]  # in microsec
    cycle_triggers = np.array(trigger_info[camera_category])

    if num_triggers is None:
        assert (
            recording_duration_s is not None
        ), "Must provide `num_triggers` or `recording_duration_s`"
        
        # num_cycles = int(recording_duration_s / cycle_duration)
        # num_triggers = int(recording_duration_s / cycle_duration) * len(cycle_triggers)
        recording_duration_us = recording_duration_s * 1e6
        num_cycles = int(recording_duration_us / cycle_duration)
        num_triggers = int(recording_duration_us / cycle_duration) * len(cycle_triggers)

    else:
        num_cycles = int(np.ceil(num_triggers / len(cycle_triggers)))

    cycle_start_times = np.arange(num_cycles) * cycle_duration
    trigger_times = (cycle_triggers[None, :] + cycle_start_times[:, None]).flatten()
    return trigger_times[:num_triggers]


def estimate_timestamps(config_path, metadata_path, camera_category="top_basler"):
    """
    Estimate the timestamps (in microseconds) of frames from a recorded video. The
    timestamps are reconstructed from the microcontroller trigger times and then
    filtered to remove dropped frames. It is assumed that the first frame of the video
    was not dropped (i.e. it corresponds to the first trigger).

    Parameters
    ----------
    config_path : str
        Path to the configuration file for a recording session.

    metadata_path : str
        Path to the metadata file for the video.

    camera_category : str, default="top_basler"
        Category of the camera for which to estimate timestamps. Must be one of:
        ["top_basler", "bottom_basler", "azure"]. If a single camera was used, the
        category should be "top_basler".

    Returns
    -------
    timestamps : np.ndarray
        Array of estimated timestamps (in microseconds) for each frame in the video.

    frame_indexes : np.ndarray
        Array of indices of captured frames (see `estimate_frame_indexes`).

    dropped_frames : np.ndarray
        Array of indices of dropped frames (see `estimate_frame_indexes`).
    """
    # Estimate frame indexes
    camera_hw_timestamps = np.loadtxt(metadata_path, delimiter=",", skiprows=1)[:, 1]
    if "basler" in camera_category:
        camera_hw_timestamps /= 1e3  # Convert from nanoseconds to microseconds
    frame_indexes, dropped_frames = estimate_frame_indexes(camera_hw_timestamps)

    # Reconstruct trigger times
    num_triggers = frame_indexes.max() + 1
    trigger_times = get_trigger_times(config_path, camera_category, num_triggers)

    # Estimate timestamps
    timestamps = trigger_times[frame_indexes]
    return timestamps, frame_indexes, dropped_frames


def query_trigger_data(trigger_data_path, pin, query_times=None):
    """
    Query the state of a microcontroller pin based on the record of states in a trigger data file.

    Parameters
    ----------
    trigger_data_path : str
        Path to the trigger data file.

    pin : int
        Pin number to query.

    query_times : np.ndarray or None, optional
        If None (default): return the state of the pin at all times recorded in the file.
        If np.ndarray: array of times (in microseconds) at which to query the pin state.

    Returns
    -------
    pin_states : np.ndarray
        Pin states at the queried times.
    """
    times, pins, states = np.loadtxt(trigger_data_path, delimiter=",", skiprows=1).T
    assert np.any(pins == pin), f"Pin {pin} not found in trigger data file."

    if query_times is None:
        return states[pins == pin], times[pins == pin]
    
    else:
        times, states = times[pins == pin], states[pins == pin]
        assert (
            query_times.min() >= times.min()
        ), "Some query times are earlier than the first logged pin state."

        pin_states = states[times.searchsorted(query_times, side="right") - 1]
        return pin_states
