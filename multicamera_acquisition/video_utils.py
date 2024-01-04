import av
import datetime
import os
import subprocess
import numpy as np


def count_frames(file_name):
    if os.path.exists(file_name):
        try:
            with av.open(file_name, "r") as reader:
                return reader.streams.video[0].frames
        except Exception as e:
            print(e)
    else:
        print("File does not exist")


def read_frames(
    filename,
    frames,
    threads=6,
    fps=30,
    pixel_format="gray8",
    frame_size=(640, 576),
    slices=24,
    slicecrc=1,
    get_cmd=False,
):
    """Reads in frames from the .mp4/.avi file using a pipe from ffmpeg.
    Args:
        filename (str): filename to get frames from
        frames (list or 1d numpy array): list of frames to grab
        threads (int): number of threads to use for decode
        fps (int): frame rate of camera in Hz
        pixel_format (str): ffmpeg pixel format of data
        frame_size (str): wxh frame size in pixels
        slices (int): number of slices to use for decode
        slicecrc (int): check integrity of slices
    Returns:
        3d numpy array:  frames x h x w
    """

    command = [
        "ffmpeg",
        "-loglevel",
        "fatal",
        "-ss",
        str(datetime.timedelta(seconds=frames[0] / fps)),
        "-i",
        filename,
        "-vframes",
        str(len(frames)),
        "-f",
        "image2pipe",
        "-s",
        "{:d}x{:d}".format(frame_size[0], frame_size[1]),
        "-pix_fmt",
        pixel_format,
        "-threads",
        str(threads),
        "-slices",
        str(slices),
        "-slicecrc",
        str(slicecrc),
        "-pix_fmt",
        "gray16",
        "-vcodec",
        "rawvideo",
        "-",
    ]

    if get_cmd:
        return command

    pipe = subprocess.Popen(command, stderr=subprocess.PIPE, stdout=subprocess.PIPE)
    out, err = pipe.communicate()
    if err:
        print("error", err)
        return None
    video = np.frombuffer(out, dtype="uint16").reshape(
        (len(frames), frame_size[1], frame_size[0])
    )
    return video
