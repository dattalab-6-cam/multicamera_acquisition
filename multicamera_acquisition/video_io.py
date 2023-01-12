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


def write_frames(
    filename,
    frames,
    threads=6,
    fps=30,
    crf=10,
    pixel_format="gray8",
    codec="ffv1",
    pipe=None,
    slices=24,
    slicecrc=1,
):
    """
    Write frames to a video file.
    Parameters
    ----------
    filename : str
        The name of the file to write.
    frames : ndarray
        The frames to write.  The shape of the array should be
        (n_frames, height, width).  The dtype should be uint8.
    threads : int (default: 6)
        The number of threads to use for encoding.
    fps : int (default: 30)
        The number of frames per second to write.
    crf : int (default: 10)
        The constant rate factor to use for encoding.  Lower values
        result in higher quality.
    pixel_format : str (default: "gray8")
        The pixel format to use for encoding.  Valid values are
        "gray8", "gray16le", "gray16be", "bgr24", "rgb24",
    codec : str (default: "ffv1")
        The codec to use for encoding.  Valid values are "ffv1",
        "h264", "h265", "mpeg4", "vp8", "vp9".
     pipe (subprocess.Popen, optional): The current pipe to write frames. If None,
        creates a pipe. Defaults to None.
    slices (int, optional): Each frame is split into this number of slices.
        This affects multithreading performance, as well as filesize: Increasing
        the number of slices might speed up performance, but also increases the filesize. Defaults to 24.
    slicecrc (int, optional): 0=off, 1=on
        Enabling this option adds CRC information to each slice. This makes
        it possible for a decoder to detect errors in the bitstream, rather than
        blindly decoding a broken slice.. Defaults to 1.
    Returns
    -------
    pipe : subprocess.Popen
        The pipe to write frames.
    """

    frame_size = "{0:d}x{1:d}".format(frames.shape[2], frames.shape[1])
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "fatal",
        "-framerate",
        str(fps),
        "-f",
        "rawvideo",
        "-s",
        frame_size,
        "-pix_fmt",
        pixel_format,
        "-i",
        "-",
        "-an",
        "-crf",
        str(crf),
        "-vcodec",
        codec,
        "-preset",
        "ultrafast",
        "-threads",
        str(threads),
        "-slices",
        str(slices),
        "-slicecrc",
        str(slicecrc),
        "-r",
        str(fps),
        filename,
    ]

    if not pipe:
        pipe = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    dtype = np.uint16 if pixel_format.startswith("gray16") else np.uint8
    for i in range(frames.shape[0]):
        pipe.stdin.write(frames[i, :, :].astype(dtype).tobytes())
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
