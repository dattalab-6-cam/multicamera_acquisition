import yaml

from multicamera_acquisition.config.default_display_config import \
    default_display_config

import pdb


def recursive_update(old_dict, updates):
    """ Recursively update a dictionary with another dictionary.

    Parameters
    ----------
    old_dict : dict
        The dictionary to be updated.
    updates : dict  
        The dictionary containing the updates.

    """
    for key, value in updates.items():
        if key in old_dict and isinstance(old_dict[key], dict) and isinstance(value, dict):
            # If both config and updates have this key as a dictionary, recurse
            recursive_update(old_dict[key], value)
        else:
            # Otherwise, update the value directly
            old_dict[key] = value


def dict_update_with_precedence(*args):
    """ Update a series of dictionaries, in decreasing order of precedence.

    Parameters
    ----------
    *args : dict
        The dictionaries to be updated, in decreasing order of precedence.

    Returns
    -------
    final_config : dict
        The final, updated dictionary.

    Examples:
    ---------
    >>> hard_coded_defaults = {'my_forgotten_param': {"got it?": "got it!"}, 'key1': 'default1', 'key2': 'default2'}
    >>> yaml_file_config = {'key2': 'yaml2', 'key3': 'yaml3'}
    >>> runtime_kwargs = {'key3': 'runtime3', 'key4': 'runtime4'}
    >>> final_config = dict_update_with_precedence(runtime_kwargs, yaml_file_config, hard_coded_defaults)
    >>> print(final_config)
    # {'my_forgotten_param': {'got it?': 'got it!'}, 'key1': 'default1', 'key2': 'yaml2', 'key3': 'runtime3', 'key4': 'runtime4'}

    """
    # Start with an empty dict
    final_config = {}

    # Add values from the arguments in reverse order, i.e. starting with the lowest precedence
    for config_dict in reversed(args):
        recursive_update(final_config, config_dict)

    return final_config


def add_rt_display_params_to_config(recording_config, display_params=None):
    """Add display params to a recording config.

    If display_params is None, the default display params will be used.
    Otherwise, the default display params will be overwritten with any
    user-provided display params.
    """
    recording_config["rt_display_params"] = default_display_config()
    if display_params is not None:
        for key in display_params.keys():
            if key in ALL_DISPLAY_PARAMS:
                recording_config["rt_display_params"][key] = display_params[key]
            else:
                raise ValueError(f"Unrecognized display param: {key}")
    return recording_config


def load_config(config_filepath):
    """Load a recording config from a file.
    """
    with open(config_filepath, "r") as f:
        recording_config = yaml.load(f, Loader=yaml.FullLoader)
    return recording_config


def save_config(config_filepath, recording_config):
    """Save a recording config to a file.
    """
    with open(config_filepath, "w") as f:
        yaml.dump(recording_config, f)
    return


def validate_recording_config(recording_config):
    """Validate a recording config dict.

    This function checks that the recording config dict is valid, 
    and raises an error if it is not.
    """

    # Ensure that the recording config is a dict
    if not isinstance(recording_config, dict):
        raise TypeError("Recording config must be a dict")

    # Ensure that the recording config has a "cameras" key
    if "cameras" not in recording_config.keys():
        raise ValueError("Recording config must have a 'cameras' key")

    # Ensure that all cameras are recognized brands
    for camera_name in recording_config["cameras"].keys():
        if recording_config["cameras"][camera_name]["brand"] not in ["basler", "basler_emulated", "azure"]:
            raise ValueError(f"Unsupported camera brand: {recording_config['cameras'][camera_name]['brand']}")

    # Ensure that each IR camera has the same FPS
    all_fps = []
    for camera_name in recording_config["cameras"].keys():
        if recording_config["cameras"][camera_name]["brand"] in ["basler", "basler_emulated"]:
            all_fps.append(recording_config["cameras"][camera_name]["fps"])
    if len(set(all_fps)) > 1:
        raise ValueError("All IR cameras must have the same FPS")
    else: 
        fps = all_fps[0]

    # Ensure that the requested frame rate is a multiple of the azure's 30 fps rate
    if fps % 30 != 0:
        raise ValueError("Framerate must be a multiple of the Azure's frame rate (30)")

    # Ensure that the requested frame rate is a multiple of the display frame rate
    # if fps % recording_config["rt_display_params"]["display_fps"] != 0:
    #     raise ValueError("Real-time framerate must be a factor of the capture frame rate")
