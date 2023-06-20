import subprocess
import numpy as np
import av
import os
import datetime


def count_frames(file_name):
    if os.path.exists(file_name):
        try:
            with av.open(file_name, "r") as reader:
                return reader.streams.video[0].frames
        except Exception as e:
            print(e)
    else:
        print("File does not exist")


def write_frame(
    filename,
    frame,
    fps=30,
    quality=15,
    pixel_format="grey8",
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
    if not pipe:
        frame_size = "{0:d}x{1:d}".format(frame.shape[1], frame.shape[0])
        command = [
            "ffmpeg",
            "-y",
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            pixel_format,
            "-s",
            frame_size,
            "-r",
            str(fps),
            "-i",
            "-",
            "-an",
        ]

        if gpu is not None:
            command += [
                "-c:v",
                "h264_nvenc",
                "-preset",
                "fast",
                "-qp",
                str(quality),
                "-gpu",
                str(gpu),
                "-vsync",
                "0",
                "-2pass",
                "0",
            ]

        else:
            command += [
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                str(quality),
            ]
        command += ["-threads", "4", "-pix_fmt", "yuv420p", str(filename)]
        # print(' '.join(command))
        # print(frame.shape)
        pipe = subprocess.Popen(
            command, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL
        )
    if pixel_format == "gray8":
        pipe.stdin.write(frame.astype(np.uint8).tobytes())
    elif pixel_format == "gray16":
        pipe.stdin.write(frame.astype(np.uint16).tobytes())
    return pipe


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
