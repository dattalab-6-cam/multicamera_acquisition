import yaml
from multicamera_acquisition.interfaces.config import create_full_camera_default_config
import pdb


def load_config(config_filepath):
    """Load a recording config from a file."""
    with open(config_filepath, "r") as f:
        recording_config = yaml.load(f, Loader=yaml.FullLoader)
    return recording_config


def save_config(config_filepath, recording_config):
    """Save a recording config to a file."""
    with open(config_filepath, "w") as f:
        yaml.dump(recording_config, f)
    return


def validate_recording_config(recording_config):
    """Validate a recording config dict.

    This function checks that the recording config dict is valid,
    and raises an error if it is not.

    # TODO: warn user if use mcu is False but there is a lot of MCU config in the config file
    """

    # Ensure that the recording config is a dict
    if not isinstance(recording_config, dict):
        raise TypeError("Recording config must be a dict")

    # Ensure that the recording config has a "cameras" key
    if "cameras" not in recording_config.keys():
        raise ValueError("Recording config must have a 'cameras' key")

    # Ensure that all cameras are recognized brands
    for camera_name in recording_config["cameras"].keys():
        if recording_config["cameras"][camera_name]["brand"] not in [
            "basler",
            "basler_emulated",
            "azure",
        ]:
            raise ValueError(
                f"Unsupported camera brand: {recording_config['cameras'][camera_name]['brand']}"
            )

    # Warn user that fps for baslers / azures is deprecated
    for camera_name in recording_config["cameras"].keys():
        if "fps" in recording_config["cameras"][camera_name].keys():
            print(
                "WARNING: fps is deprecated for Basler camera configs (unecessary) and azure cameras (only 30 fps supported)."
            )

    # Ensure that the requested frame rate is a multiple of the azure's 30 fps rate
    if recording_config["globals"]["fps"] % 30 != 0:
        raise ValueError("Framerate must be a multiple of the Azure's frame rate (30)")


    ### FPS checks ###
    # Warn user if writers don't have fps params
    for camera_name in recording_config["cameras"].keys():
        ir_fpses = []
        if "fps" not in recording_config["cameras"][camera_name]["writer"].keys():
            raise ValueError(f"No fps specified for writer {camera_name}.")
        elif recording_config["cameras"][camera_name]["brand"] not in ["azure", "lucid"]:
            ir_fpses.append(recording_config["cameras"][camera_name]["writer"]["fps"])

    # Warn user if writer fps don't all match, except for azure cameras
    if len(set(ir_fpses)) > 1:
        raise ValueError("All Basler camera fps must match.")

    # Warn user if global fps does not match fps in individual writers
    if recording_config["globals"]["fps"] != ir_fpses[0]:
        raise ValueError("Global fps must match fps in individual writers.")


def recursive_update(old_dict, updates):
    """Recursively update a dictionary with another dictionary.

    Parameters
    ----------
    old_dict : dict
        The dictionary to be updated.
    updates : dict
        The dictionary containing the updates.

    """
    for key, value in updates.items():
        if (
            key in old_dict
            and isinstance(old_dict[key], dict)
            and isinstance(value, dict)
        ):
            # If both config and updates have this key as a dictionary, recurse
            recursive_update(old_dict[key], value)
        else:
            # Otherwise, update the value directly
            old_dict[key] = value


def dict_update_with_precedence(*args):
    """Update a series of dictionaries, in decreasing order of precedence.

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
