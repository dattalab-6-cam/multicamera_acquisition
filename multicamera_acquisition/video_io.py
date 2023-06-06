import subprocess
import numpy as np
import av
import os
import datetime


def count_frames(file_name):
    if os.path.exists(file_name):
        with av.open(file_name, "r") as reader:
            return reader.streams.video[0].frames
    else:
        print("File does not exist")


def write_frame(
    filename,
    frame,
    fps=30,
    quality=15,
    gpu=None,
    pipe=None,
):
    """
    Write frames to a video file.
    Parameters
    ----------
    filename : str
        The name of the file to write.
    frame : ndarray
        The frame to write.
    fps : int (default: 30)
        The number of frames per second to write.
    gpu: int (default=False)
        Which GPU to use for encoding. If None, the CPU is used.
    pipe (subprocess.Popen, optional): The current pipe to write frames. If None,
        creates a pipe. Defaults to None.
    Returns
    -------
    pipe : subprocess.Popen
        The pipe to write frames.
    """
    
    frame_size = "{0:d}x{1:d}".format(frame.shape[1], frame.shape[0])
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-vcodec",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-s",
        frame_size,
        "-r",
        str(fps),
        "-i",
        "-",
        "-an"]

    if gpu is not None: command += [
        "-c:v",
        "h264_nvenc",
        "-preset",
        'fast',
        "-qp", str(quality),
        "-gpu", str(gpu),
        "-vsync", "0",
        "-2pass", "0",
        ]

    else: command += [   
        "-c:v",
        'libx264',
        "-preset",
        'ultrafast',
        "-crf",
        str(quality),]
    command += [   
        "-pix_fmt",
        "yuv420p",
        filename]

    if not pipe:
        pipe = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    pipe.stdin.write(frame.astype(np.uint8).tobytes())
    return pipe
