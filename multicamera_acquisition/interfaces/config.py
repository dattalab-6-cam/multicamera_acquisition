from multicamera_acquisition.interfaces.camera_basler import BaslerCamera, EmulatedBaslerCamera
from multicamera_acquisition.config.config import dict_update_with_precedence

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


def partial_config_from_camera_list(camera_list, fps):
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

    fps : int
        The desired frame rate for the recording.

        Other optional parameters depend on the camera brand. It is also possible to control the Writer parameters for each camera. The syntax is 
        flat (not nested) and follows the same rules as the camera params. For example, to set
        the quality of the writer for the "top" camera to 90, you would do:
            {"name": "top", "quality": 90}
        (It follows that camera param names and writer param names must not overlap!)
    """

    # Set up the partial config
    partial_config = {}
    partial_config["cameras"] = {}

    for camera_dict in camera_list:

        # Set up the nested config dicts
        camera_name = camera_dict["name"]
        partial_config["cameras"][camera_name] = {}
        partial_config["cameras"][camera_name]["writer"] = {}
        partial_config["cameras"][camera_name]["display"] = {}

        # Add the params to the partial config
        for key in list(camera_dict.keys()):
            if key in ALL_CAM_PARAMS:
                partial_config["cameras"][camera_name][key] = camera_dict[key]
            elif key in ALL_WRITER_PARAMS:
                partial_config["cameras"][camera_name]["writer"][key] = camera_dict[key]
            elif key in ALL_DISPLAY_PARAMS:
                partial_config["cameras"][camera_name]["display"][key] = camera_dict[key]

        # Add fps to this camera
        # NB: we don't allow the user to specify fps per camera, since it's a global param
        partial_config["cameras"][camera_name]["fps"] = fps

    return partial_config


def create_full_camera_default_config(partial_config):
    """Create a full, default recording config for the cameras + writers.

    Parameters
    ----------
    partial_config : dict
        A partial config for cameras + their writers, generated from any user input.

    Returns
    -------
    recording_config : dict
        The full recording config, including all camera and writer params, with 
        all remaining required params filled in with defaults.
    """

    full_recording_config = {}
    full_recording_config["cameras"] = {}

    camera_names = list(partial_config["cameras"].keys())
    assert len(camera_names) > 0, "No cameras found in configs"
    assert len(set(camera_names)) == len(camera_names), "Duplicate camera names found in config"

    for camera_name in camera_names:
        fps = partial_config["cameras"][camera_name]["fps"]

        cam_config = {}
        cam_config["name"] = camera_name

        # Get the camera's brand and id from the partial config
        try:
            cam_config["brand"] = partial_config["cameras"][camera_name]["brand"]
            cam_config["id"] = partial_config["cameras"][camera_name]["id"]
        except KeyError:
            raise KeyError(f"Camera {camera_name} must have a brand and id")

        # Find the correct defaults (both camera and writer configs)
        if cam_config["brand"] == "basler":
            default_cam_conf = BaslerCamera.default_camera_config(fps)
            default_writer_conf = BaslerCamera.default_writer_config(fps)
            defaults = {**default_cam_conf, "writer": default_writer_conf}
        elif cam_config["brand"] == "basler_emulated":
            default_cam_conf = EmulatedBaslerCamera.default_camera_config(fps)
            default_writer_conf = EmulatedBaslerCamera.default_writer_config(fps)
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
            partial_config["cameras"][camera_name],
            defaults,
        )

        # Set display to false if not already specified
        if "display" not in cam_config:
            cam_config["display"] = False

        # Save this camera's config in the recording config
        full_recording_config["cameras"][camera_name] = cam_config

    return full_recording_config