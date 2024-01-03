import subprocess
import numpy as np
import av
import os
import datetime
import cv2
import logging


def count_frames(file_name):
    if os.path.exists(file_name):
        try:
            with av.open(file_name, "r") as reader:
                return reader.streams.video[0].frames
        except Exception as e:
            print(e)
    else:
        print("File does not exist")


def create_ffmpeg_pipe_command(
    filename,
    frame,
    fps,
    quality=15,
    pixel_format="gray8",
    gpu=None,
    depth=False,
):
    """Create a pipe for ffmpeg"""
    # Get the size of the frame
    frame_size = "{0:d}x{1:d}".format(frame.shape[1], frame.shape[0])
    logging.log(logging.DEBUG, f"FRAME SHAPE {frame.shape}")
    if not depth:
        # Prepare the basic ffmpeg command
        command = [
            "ffmpeg",
            "-loglevel",
            "fatal",
            "-y",  # Overwrite existing file without asking
            "-f",
            "rawvideo",
            "-vcodec",
            "rawvideo",
            "-pix_fmt",
            pixel_format,  # Input pixel format (gray8, gray16, etc.)
            "-s",
            frame_size,  # Input frame size
            "-r",
            str(fps),  # Input frames per second
            "-i",
            "-",  # Read input from stdin
            "-an",  # No audio
        ]

        if gpu is not None:
            # GPU encoding options using h264_nvenc codec
            command += [
                "-c:v",
                "h264_nvenc",  # "av1_nvenc", "h264_nvenc" "hevc_nvenc"  # TODO: this still requires nvenc to be installed?
                "-preset",
                "p1",
                "-qp",
                str(quality),  # Video quality (0-51, lower is better)
                "-gpu",
                str(gpu),  # Specify which GPU to use for encoding
                "-vsync",
                "0",  # Disable frame rate synchronization
                "-2pass",
                "0",  # Disable two-pass encoding
            ]
        else:
            # CPU encoding options using libx264 codec
            if pixel_format in ["gray16", "grey16"]:
                command += ["-vcodec", "ffv1"]
            else:
                command += ["-c:v", "libx264"]
            command += [
                "-preset",
                "ultrafast",
                "-crf",
                str(quality),  # Video quality (0-51, lower is better)
                "-threads",
                "4",  # Number of threads to use for encoding
            ]

        if pixel_format not in ["gray16", "grey16"]:
            command += ["-pix_fmt", "yuv420p"]  # Output pixel format

        # Additional options for output format and filename
        command += [str(filename)]  # Output filename
    else:
        codec = "ffv1"
        command = [
            "ffmpeg",
            "-y",
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
            "-vcodec",
            codec,
            # "-c:v",
            # "libx264",
            str(filename),
        ]

    # log
    logging.log(logging.DEBUG, f"filename: {' '.join(command)}")

    return command


bytes_to_pad = np.repeat(np.uint8(128), int((1200 * 1920) / 2)).tobytes()


def write_frame(
    filename,
    frame,
    fps,
    quality=15,
    pixel_format="gray8",
    gpu=None,
    pipe=None,
    depth=False,
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
    pipe (subprocess.Popen, optional): The current pipe to write frames. If None, creates a pipe. Defaults to None.

    Returns
    -------
    pipe : subprocess.Popen
        The pipe to write frames.
    """

    if not pipe:
        command = create_ffmpeg_pipe_command(
            filename,
            frame,
            fps,
            quality=quality,
            pixel_format=pixel_format,
            gpu=gpu,
            depth=depth,
        )

        # Create a subprocess pipe to write frames
        with open(f"{str(filename)}.stdout.txt", "w") as f_out, open(
            f"{str(filename)}.stderr.txt", "w"
        ) as f_err:
            pipe = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=f_out,  # standard output is redirected to 'stdout.txt'
                stderr=f_err,  # standard error is redirected to 'stderr.txt'
            )

    try:
        if pixel_format == "gray8":
            # Convert the frame to uint8 and write it to the pipe's stdin
            # additionally, convert to yuv444p/yuv420 format
            pipe.stdin.write(frame.astype(np.uint8).tobytes())
        elif pixel_format == "gray16":
            # Convert the frame to uint16 and write it to the pipe's stdin
            pipe.stdin.write(frame.astype(np.uint16).tobytes())
    except BrokenPipeError as e:
        logging.log(
            logging.WARNING,
            f"BrokenPipeError. Are video files >5GB & FAT32? Check STDERR {e}.",
        )

        pipe = None
        print("ADD THIS BACK IN")
        # raise BrokenPipeError

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
