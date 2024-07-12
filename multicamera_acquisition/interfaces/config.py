import itertools

from multicamera_acquisition.config import dict_update_with_precedence
from multicamera_acquisition.interfaces.camera_basler import (
    BaslerCamera,
    EmulatedBaslerCamera,
)

# Per-camera allowed parameter names
ALL_CAM_PARAMS = [
    "name",
    "id",
    "roi",
    "gain",
    "gamma",
    "exposure",
    "brand",
    "fps",
]

# Not exhaustive, but any lower-level ffmpeg or nvc params
# shouldn't be passed in this way.
ALL_WRITER_PARAMS = [
    "gpu",
]

ALL_DISPLAY_PARAMS = [
    "downsample",  # ie spatial downsample
    "display_every_n",  # ie temporal downsample
    "display_range",  # (min, max) for display colormap
    "display_size",  # int
    "display_frames",  # bool
]

ALL_TRIGGER_PARAMS = [
    "trigger_type",
    "acquisition_mode",
    "trigger_source",
    "trigger_selector",
    "trigger_activation",
]

# Since we will match params 1:1 with the user-provided camera list, we need to
# ensure that the param names are never redundant.
# TODO: could decide to un-flatten the camera list, which would also solve this.
for pair in itertools.combinations(
    [
        ALL_CAM_PARAMS,
        ALL_WRITER_PARAMS,
        ALL_DISPLAY_PARAMS,
        ALL_TRIGGER_PARAMS,
    ],
    2,
):
    assert all(
        [param not in pair[1] for param in pair[0]]
    ), f"Redundant param names: {pair}"


def partial_config_from_camera_list(camera_list):
    """Create a partial recording config from a list of camera dicts.

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
            exposure : int
                The exposure time for the camera, in microseconds.
            display_frames : bool
                Whether to display the camera's feed in real-time.
            gain: int
                The gain for the camera, in (units?). (TODO: valid ranges?)
            gamma: float
                The gamma for the camera. (TODO: valid ranges?)

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
        partial_config["cameras"][camera_name]["trigger"] = {}

        # Add the params to the partial config
        for key in list(camera_dict.keys()):
            if key in ALL_CAM_PARAMS:
                partial_config["cameras"][camera_name][key] = camera_dict[key]
            elif key in ALL_WRITER_PARAMS:
                partial_config["cameras"][camera_name]["writer"][key] = camera_dict[key]
            elif key in ALL_DISPLAY_PARAMS:
                partial_config["cameras"][camera_name]["display"][key] = camera_dict[
                    key
                ]
            elif key in ALL_TRIGGER_PARAMS:
                partial_config["cameras"][camera_name]["trigger"][key] = camera_dict[
                    key
                ]

    return partial_config


def create_full_camera_default_config(partial_config, fps):
    """Create a full, default recording config for the cameras + writers.

    Parameters
    ----------
    partial_config : dict
        A partial config for cameras + their writers, generated from any user input.

    fps : int
        The desired fps for the recordings.

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
    assert len(set(camera_names)) == len(
        camera_names
    ), "Duplicate camera names found in config"

    for camera_name in camera_names:
        # Create what will become the full config for this camera
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
            default_cam_conf = BaslerCamera.default_camera_config().copy()
            default_writer_conf = BaslerCamera.default_writer_config(fps).copy()
            defaults = {**default_cam_conf, "writer": default_writer_conf}
        elif cam_config["brand"] == "basler_emulated":
            default_cam_conf = EmulatedBaslerCamera.default_camera_config().copy()
            default_writer_conf = EmulatedBaslerCamera.default_writer_config(fps).copy()
            defaults = {**default_cam_conf, "writer": default_writer_conf}
        elif cam_config["brand"] == "azure":
            from multicamera_acquisition.interfaces.camera_azure import AzureCamera

            default_cam_conf = AzureCamera.default_camera_config().copy()
            default_writer_conf = AzureCamera.default_writer_config(
                30
            ).copy()  # TODO: un-hardcode this even tho it wont change
            defaults = {**default_cam_conf, "writer": default_writer_conf}

        elif cam_config["brand"] == "uvc":
            from multicamera_acquisition.interfaces.camera_uvc import UVCCamera

            default_cam_conf = UVCCamera.default_camera_config().copy()
            default_writer_conf = UVCCamera.default_writer_config(fps).copy()
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
        if "display_frames" not in cam_config["display"]:
            cam_config["display"]["display_frames"] = False

        # Save this camera's config in the recording config
        full_recording_config["cameras"][camera_name] = cam_config

    return full_recording_config
