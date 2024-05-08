import glob
import logging
import multiprocessing as mp
import os
import queue as sync_queue
import time
import tkinter as tk

import cv2
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import PIL
from PIL import ImageTk

from multicamera_acquisition.logging_utils import setup_child_logger


class MultiDisplay(mp.Process):
    def __init__(
        self,
        queues,
        camera_list,
        display_ranges,
        config=None,
        logger_queue=None,
        logging_level=logging.DEBUG,
    ):
        super().__init__()

        # Store params
        self.config = config
        self.queues = queues
        self.logger_queue = logger_queue
        self.logging_level = logging_level
        self.camera_list = camera_list
        self.display_ranges = display_ranges
        self.num_cameras = len(camera_list)

        # Set up the config
        if config is None:
            self.config = self.default_MultiDisplay_config().copy()
        else:
            self.validate_config()

    def _init_layout(self):
        root = tk.Tk()
        xdim = self.config["display_size"][0] * self.config["cameras_per_row"]
        ydim = self.config["display_size"][1] * int(
            np.ceil(self.num_cameras / self.config["cameras_per_row"])
        )
        root.title("Camera view")  # this is the title of the window
        root.geometry(f"{xdim}x{ydim}")  # this is the size of the window

        rowi = 0
        labels = []
        # create a label to hold the image
        for ci, camera_name in enumerate(self.camera_list):
            # create the camera name label
            label_text = tk.Label(root, text=camera_name)
            label_text.grid(
                row=rowi, column=ci % self.config["cameras_per_row"], sticky="nsew"
            )

            # create the camerea image label
            label = tk.Label(root)  # this is where the image will go
            label.grid(
                row=rowi + 1, column=ci % self.config["cameras_per_row"], sticky="nsew"
            )

            if (ci + 1) % self.config["cameras_per_row"] == 0:
                rowi += 2

            labels.append(label)

        for i in range(self.config["cameras_per_row"]):
            root.grid_columnconfigure(i, weight=1)
        for i in range(rowi):
            root.grid_rowconfigure(i, weight=1)

        return root, labels

    def _fetch_image(self, queue, camera_name, log_if_error):
        try:
            # Note: earlier code used queue.qsize() > 1; have not yet verified
            # that queue.empty performs the same
            if not queue.empty():
                while not queue.empty():
                    img = get_latest(
                        queue, timeout=0.01
                    )  # empties the queue in case we've fallen behind?
            else:
                img = queue.get(timeout=0.01)

        except Exception as error:
            if log_if_error:
                logging.info("{}: Timeout occurred {}".format(camera_name, str(error)))
            return None
        return img

    def run(self):
        # Set the process group ID to to the process ID so it isn't affected by the main process's stop signal
        os.setpgid(0, 0)

        # Set up the logger
        if self.logger_queue is None:
            # Just use the root logger
            self.logger = logging.getLogger()
        elif isinstance(self.logger_queue, mp.queues.Queue):
            # Create a logger for this process
            # (it will automatically include the process name in the log output)
            logger = setup_child_logger(self.logger_queue, level=self.logging_level)
            self.logger = logger
            self.logger.debug("Created logger")
        else:
            raise ValueError("logger_queue must be a multiprocessing.Queue or None.")

        root, labels = self._init_layout()

        quit = False
        while True:
            # initialized checks to see if recording has started
            initialized = np.zeros(len(self.queues)).astype(bool)
            for qi, (queue, camera_name) in enumerate(
                zip(self.queues, self.camera_list)
            ):
                img = self._fetch_image(
                    queue, camera_name, log_if_error=initialized[qi]
                )

                if img is not None:

                    # If acq sends an empty tuple, it means it's done
                    if len(img) == 0:
                        quit = True
                        self.logger.debug("No data, quitting...")
                        break

                    # retrieve frame
                    else:
                        initialized[qi] = True
                        frame = format_frame(
                            img,
                            display_size=self.config["display_size"],
                            display_range=self.display_ranges[qi],
                            is_depth=img.dtype == np.uint16 or ("lucid" in camera_name),
                        )

                        # update label with new image
                        img = ImageTk.PhotoImage(frame)
                        labels[qi].config(image=img)
                        labels[qi].image = img
                else:
                    continue

            if quit:
                break
            # update tkinter window
            root.update()
        root.destroy()

        # Here, we empty the queues to make sure we don't leave any data in them.
        # If there are images left in the queues, the main thread won't finish!
        self.logger.debug("Emptying queues...")
        for qi, (queue, camera_name) in enumerate(zip(self.queues, self.camera_list)):
            data = self._fetch_image(queue, camera_name, log_if_error=initialized[qi])

        self.logger.debug("MultiDisplay process finished")

    @staticmethod
    def default_MultiDisplay_config():
        return {
            "display_every_n": 3,
            "cameras_per_row": 3,
            "display_size": (300, 300),  # TODO: allow this to be per-camera
        }

    def validate_config(self):
        return True
        # return config.validate_against_schema(self.config, self.get_config_schema())


def get_latest(queue, timeout=0.1):
    start_time = time.time()
    try:
        item = queue.get(timeout=timeout)
        while True:
            try:
                elapsed_time = time.time() - start_time
                remaining_time = timeout - elapsed_time

                if remaining_time > 0:
                    next_item = queue.get(timeout=remaining_time)
                    item = next_item
                else:
                    break
            except sync_queue.Empty:
                break
    except sync_queue.Empty:
        item = None

    return item


def format_frame(frame, display_size, display_range, is_depth):
    frame = cv2.resize(frame, display_size)

    # normalize in range
    if display_range is not None:
        frame = normalize_array(
            frame,
            min_value=display_range[0],
            max_value=display_range[1],
        ).astype(np.uint8)
    else:
        frame = normalize_array(frame).astype(np.uint8)

    # int16 should be azure data
    if is_depth:
        # Convert frame to turbo/jet colormap
        frame = cv2.applyColorMap(frame, cv2.COLORMAP_TURBO)

    return PIL.Image.fromarray(frame)


def normalize_array(frame, min_value=None, max_value=None):
    if min_value is None:
        min_value = np.min(frame)
        max_value = np.max(frame)
    frame[frame > max_value] = max_value
    frame[frame < min_value] = min_value
    # frame = np.clip(frame, min_value, max_value)  # Ensure values are in the range [min_value, max_value]
    frame = (
        (frame - min_value) / (max_value - min_value)
    ) * 255.0  # Normalize to [0, 255]
    return frame.astype(np.uint8)


def plot_video_stats(csv_path, name):
    # Load the data
    df = pd.read_csv(csv_path)

    # Set up plot
    fig, axs = plt.subplots(
        ncols=1,
        nrows=5,
        gridspec_kw={"height_ratios": [1, 1, 1, 1, 1]},
        figsize=(10, 8),
        sharex=True,
    )

    # Plot frame diffs (ie, check for dropped frames)
    axs[0].set_title(f"{name}: frame diff (dropped frames?)")
    axs[0].plot(np.diff(df.frame_id.values))

    # Plot camera timestamp diffs
    diffs = np.diff(df.frame_timestamp.values)
    axs[1].set_title(f"{name}: camera timestamp diff")
    axs[1].plot(diffs / np.median(diffs))

    # Plot computer timestamp diffs
    axs[2].set_title(f"{name}: computer timestamp (uid) diff")
    axs[2].plot(
        np.diff(df.frame_image_uid.values)
        / np.median(np.diff(df.frame_image_uid.values))
    )

    # Plot queue size
    axs[3].set_title(f"{name}: queue size")
    axs[3].plot(df.queue_size.values)
    axs[3].set_xlabel("Frames")
    axs[3].set_title("Queue size")

    # Plot relative occurrence of framerates
    axs[4].hist(1 / (np.diff(df.frame_timestamp.values) * 1e-9), bins=100)
    axs[4].set_xlabel("Framerate")
    axs[4].set_ylabel("Count")
    axs[4].set_title(f"{name}: framerate histogram")

    # Format plot
    plt.tight_layout()
    plt.show()

    # Print some info
    time_elapsed = (df.frame_timestamp.values[-1] - df.frame_timestamp.values[0]) * 1e-9
    avg_diffs = np.mean(diffs)
    print(f"Total time elapsed: {time_elapsed} seconds")
    print(f"Average framerate: {1 / (avg_diffs* 1e-9)} Hz")

    return


def plot_image_grid(images, display_config, camera_names, display_ranges):
    """
    Parameters
    ----------
    images : dict
        Mapping from camera names to images from that camera
    display_config : dict
        Config dictionary for a MultiDisplay
    camera_names : list
        List of camera names to plot
    display_ranges : list
        List of display ranges for each camera (ie 0-255 for uint8, 0-65535 for uint16)
    """

    cfg = display_config
    nrow = int(np.ceil(len(camera_names) / cfg["cameras_per_row"]))
    fig, ax = plt.subplots(
        nrow, cfg["cameras_per_row"], figsize=(2 * cfg["cameras_per_row"], 2 * nrow)
    )
    ax = ax.ravel()

    # plot image for each camera in display config, formatted as in Multidisplay
    for a, camera_name, rng in zip(ax, camera_names, display_ranges):
        frame = images[camera_name]
        frame = format_frame(
            frame,
            cfg["display_size"],
            rng,
            frame.dtype == np.uint16 or ("lucid" in camera_name),
        )
        a.imshow(frame)
        a.set_title(camera_name)
        a.set_xticks([])
        a.set_yticks([])

    # hide unused axes
    for a in ax[len(camera_names) :]:
        a.set_axis_off()

    fig.tight_layout()
    return fig, ax


def load_first_frames(location):
    """
    Load first frame of an acquisition for visualization

    Parameters
    ----------
    location : Path
        Directory passed to `acquire_video`
    Returns
    -------
    images : dict[str, array]
        Mapping of camera name to first frame of acquired video
    """

    images = {}
    files = list(glob.glob(str(location / "*.mp4")))
    if len(files) == 0:
        logging.log(logging.WARN, f"No recordings found at {location}")
    for f in files:
        basename = os.path.basename(f)
        cam_name = basename.split(".")[-3]
        cap = cv2.VideoCapture(f)
        if cap.isOpened():
            _, frame = cap.read()
            images[cam_name] = frame
        else:
            logging.log(logging.WARN, f"Could not read video {f}.")
    return images
