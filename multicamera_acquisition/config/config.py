import yaml

from multicamera_acquisition.config.default_display_config import \
    default_display_config
from multicamera_acquisition.interfaces.camera_basler import BaslerCamera

ALL_CAM_PARAMS = [
    "name",
    "brand",
    "serial",
    "exposure_time",
    "display",
]

ALL_WRITER_PARAMS = [
    "gpu",
    "quality",
]

ALL_DISPLAY_PARAMS = [
    "display_range",  # (min, max) for display colormap
    "display_fps",
    "display_window_name",
]

# Since we will match params 1:1 with the user-provided camera list, we need to
# ensure that the param names are never redundant.
# TODO: could decide to un-flatten the camera list, which would also solve this.
assert all([param not in ALL_CAM_PARAMS for param in ALL_WRITER_PARAMS])
assert all([param not in ALL_CAM_PARAMS for param in ALL_DISPLAY_PARAMS])
assert all([param not in ALL_WRITER_PARAMS for param in ALL_DISPLAY_PARAMS])


def create_config_from_camera_list(camera_list, baseline_recording_config=None):
    """Create a recording config from a list of camera dicts.

    If baseline_recording_config is None, each camera's config will be 
    created from the default config for the brand. If baseline_recording_config
    is a dict containing a config for the cameras, it will be used as the
    starting point for each camera's config. 

    In either case, the default config is then overwritten with any 
    user-provided config values. 

    This process is repated for the Writer config for each camera.
    """

    # Create the recording config, from the baseline one if provided
    if baseline_recording_config is None:
        recording_config = {}
        recording_config["cameras"] = {}
        baseline_camera_names = []
    else:
        recording_config = baseline_recording_config.copy()
        baseline_camera_names = list(recording_config["cameras"].keys())

    # Copy the camera list so that we don't modify the original
    # as we pop stuff out of it
    user_camera_list = camera_list.copy()  
    user_camera_dict = {cam["name"]: cam for cam in user_camera_list}

    # Iterate over the union of camera names in the camera list plus 
    # camera names in the baseline recording config.
    user_camera_list_names = [cam.pop('name') for cam in user_camera_list]
    camera_names = set(user_camera_list_names + baseline_camera_names)

    for camera_name in camera_names:

        # If the camera is in the recording config but not the user camera list,
        # then we don't need to do anything, since the user didn't specify a config.
        if camera_name not in user_camera_list_names:
            continue

        # If the camera is in the user camera list but not the recording config,
        # then we need to create a new config for it. 
        # Otherwise, use what's already in the recording config as the starting point.
        this_user_cam_dict = user_camera_dict[camera_name]
        camera_brand = this_user_cam_dict.pop("brand")
        if camera_name not in recording_config["cameras"].keys():

            # Find the correct default camera and writer configs
            if camera_brand == "basler":
                cam_config = BaslerCamera.default_camera_config()
                writer_config = BaslerCamera.default_writer_config()
            elif camera_brand == "azure":
                cam_config = AzureCamera.default_config()
                writer_config = AzureCamera.default_writer_config()
            else:
                raise NotImplementedError

        elif camera_name in recording_config["cameras"].keys():
            cam_config = recording_config["cameras"][camera_name]
            writer_config = recording_config["cameras"][camera_name]["writer"]

        # Update the camera config with any user-provided config values
        for key in this_user_cam_dict.keys():
            if key in ALL_CAM_PARAMS:
                cam_config[key] = this_user_cam_dict.pop(key)

            if key in ALL_WRITER_PARAMS:
                writer_config[key] = this_user_cam_dict.pop(key)

            if key == "display":
                cam_config[key] = this_user_cam_dict.pop(key)

        # Save this writer config into this camera's config
        cam_config["writer"] = writer_config

        # Set display to false if not already specified
        if "display" not in cam_config:
            cam_config["display"] = False

        # Save this camera's config in the recording config
        recording_config["cameras"][camera_name] = cam_config

        # Ensure we've used all the params in the camera dict, 
        # if not the user is trying to pass some param that doesn't exist
        if len(this_user_cam_dict) > 0:
            raise ValueError(
                f"Unrecognized camera params: {this_user_cam_dict.keys()}. "
                "Did you misspell a param?"
            )

    return recording_config


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
