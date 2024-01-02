import yaml

from multicamera_acquisition.config.default_display_config import \
    default_display_config
from multicamera_acquisition.interfaces.camera_basler import BaslerCamera, EmulatedBaslerCamera


# Per-camera allowed parameter names
ALL_CAM_PARAMS = [
    "name",
    "brand",
    "id",
    "exposure_time",
    "display",
]

ALL_WRITER_PARAMS = [
    "gpu",
    "quality",
]

ALL_DISPLAY_PARAMS = [
    "display_range",  # (min, max) for display colormap
    
    # "display_fps",  #TODO: these are global display params, not per camera
    # "display_window_name",
]

# Since we will match params 1:1 with the user-provided camera list, we need to
# ensure that the param names are never redundant.
# TODO: could decide to un-flatten the camera list, which would also solve this.
assert all([param not in ALL_CAM_PARAMS for param in ALL_WRITER_PARAMS])
assert all([param not in ALL_CAM_PARAMS for param in ALL_DISPLAY_PARAMS])
assert all([param not in ALL_WRITER_PARAMS for param in ALL_DISPLAY_PARAMS])


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
    for config_dict in args:
        recursive_update(final_config, config_dict)

    return final_config


def partial_config_from_camera_list(camera_list):
    """ Create a partial recording config from a list of camera dicts.

    Parameters
    ----------
    camera_list : list of dicts
        Each dict (per camera) must contain AT LEAST the following keys:
            name : str
                The name of the camera in the experiment, e.g. "top" or "side2" or "azuretop", etc.
            brand : str
                The brand of the desired camera. Currently supported: "basler", "basler_emulated", "azure"...
            id : int or str
                If int, the camera's device ID. If str, the camera's serial number.

        Other optional parameters include:
            exposure_time : int
                The exposure time for the camera, in microseconds.
            display : bool
                Whether to display the camera's feed in real-time.
            gain: int
                The gain for the camera, in (units?). (TODO: valid ranges?)

        Other optional parameters depend on the camera brand. It is also possible to control the Writer parameters for each camera. The syntax is 
        flat (not nested) and follows the same rules as the camera params. For example, to set
        the quality of the writer for the "top" camera to 90, you would do:
            {"name": "top", "quality": 90}
        (It follows that camera param names and writer param names must not overlap!)
    """
    partial_config = {}
    partial_config["cameras"] = {}
    for camera_dict in camera_list:
        camera_name = camera_dict["name"]
        partial_config["cameras"][camera_name] = {}
        for key in list(camera_dict.keys()):
            if key in ALL_CAM_PARAMS:
                partial_config["cameras"][camera_name][key] = camera_dict[key]
            elif key in ALL_WRITER_PARAMS:
                partial_config["cameras"][camera_name]["writer"][key] = camera_dict[key]
            elif key in ALL_DISPLAY_PARAMS:
                partial_config["cameras"][camera_name]["display"][key] = camera_dict[key]

    return partial_config


def create_full_camera_config(runtime_config, baseline_recording_config=None):
    """Create a full recording config for the cameras + writers.

    Parameters
    ----------
    runtime_config : dict
        The runtime config, generated from the user's camera list by partial_config_from_camera_list().

    baseline_recording_config : dict or None
        The baseline recording config, if any.

    Returns
    -------
    recording_config : dict
        The full recording config, including all camera and writer params, with all required params filled in with defaults.
    """

    full_recording_config = {}
    full_recording_config["cameras"] = {}

    # Iterate over the union of camera names in the camera list plus 
    # camera names in the baseline recording config.
    runtime_cam_names = list(runtime_config["cameras"].keys())
    if baseline_recording_config is not None:
        baseline_cam_names = list(baseline_recording_config["cameras"].keys())
    else:
        baseline_cam_names = []
    camera_names = set(runtime_cam_names + baseline_cam_names)
    assert len(camera_names) > 0, "No cameras found in configs"

    for camera_name in camera_names:

        cam_config = {}
        cam_config["name"] = camera_name

        # Get the camera's brand and id, from runtime config (higher prec) or baseline config (lower prec)
        try:
            if camera_name in runtime_cam_names:
                cam_config["brand"] = runtime_config["cameras"][camera_name]["brand"]
                cam_config["id"] = runtime_config["cameras"][camera_name]["id"]
            else:
                cam_config["brand"] = baseline_recording_config["cameras"][camera_name]["brand"]
                cam_config["id"] = baseline_recording_config["cameras"][camera_name]["id"]
        except KeyError:
            raise KeyError(f"Camera {camera_name} must have a brand and id")

        # Find the correct defaults (both camera and writer configs)
        if cam_config["brand"] == "basler":
            default_cam_conf = BaslerCamera.default_camera_config()
            default_writer_conf = BaslerCamera.default_writer_config()
            defaults = {**default_cam_conf, "writer": default_writer_conf}
        elif cam_config["brand"] == "basler_emulated":
            default_cam_conf = EmulatedBaslerCamera.default_camera_config()
            default_writer_conf = EmulatedBaslerCamera.default_writer_config()
            defaults = {**default_cam_conf, "writer": default_writer_conf}
        elif cam_config["brand"] == "azure":
            default_cam_conf = AzureCamera.default_config()
            default_writer_conf = AzureCamera.default_writer_config()
            defaults = {**default_cam_conf, "writer": default_writer_conf}
        else:
            raise NotImplementedError

        # Update this camera's config in the correct order of precedence
        cam_config = dict_update_with_precedence(
            cam_config,
            runtime_config["cameras"][camera_name] if camera_name in runtime_cam_names else {}, 
            baseline_recording_config["cameras"][camera_name] if camera_name in baseline_cam_names else {}, 
            defaults,
        )

        # Set display to false if not already specified
        if "display" not in cam_config:
            cam_config["display"] = False

        # Save this camera's config in the recording config
        full_recording_config["cameras"][camera_name] = cam_config

    return full_recording_config


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
        recording_config = yaml.load(f)
    return recording_config


def save_config(config_filepath, recording_config):
    """Save a recording config to a file.
    """
    with open(config_filepath, "w") as f:
        yaml.dump(recording_config, f)
    return


def validate_recording_config(recording_config, fps):
    """Validate a recording config dict.

    This function checks that the recording config dict is valid, 
    and raises an error if it is not.
    """

    # Ensure that the requested frame rate is a multiple of the azure's 30 fps rate
    if fps % 30 != 0:
        raise ValueError("Framerate must be a multiple of the Azure's frame rate (30)")

    # Ensure that the requested frame rate is a multiple of the display frame rate
    if fps % recording_config["rt_display_params"]["display_fps"] != 0:
        raise ValueError("Real-time framerate must be a factor of the capture frame rate")
