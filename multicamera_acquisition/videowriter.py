import subprocess
import numpy as np
import av

def count_frames(file_name):
    with av.open(file_name, "r") as reader:
        return reader.streams.video[0].frames


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