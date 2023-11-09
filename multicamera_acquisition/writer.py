from multicamera_acquisition.interfaces import get_camera
from multicamera_acquisition.video_io_ffmpeg import write_frame
from multicamera_acquisition.paths import ensure_dir
from multicamera_acquisition.interfaces.arduino import (
    packIntAsLong,
    wait_for_serial_confirmation,
)
from multicamera_acquisition.visualization import MultiDisplay

import multiprocessing as mp
import csv
import warnings
import time
import csv
from datetime import datetime, timedelta
import glob
import logging
from tqdm import tqdm
import numpy as np

import serial
from pathlib2 import Path
from multicamera_acquisition.video_io_ffmpeg import count_frames
import PyNvCodec as nvc

# for reference only
NVIDIA_SETTINGS = """
    make_pair("codec", "video codec: {'codec' : 'h264'}"),
    make_pair("preset", "nvenc preset: {'preset' : 'P4'}"),
    make_pair("tuning_info",
            "how to tune nvenc: {'tuning_info' : 'high_quality'}"),
    make_pair("profile", "h.264 profile: {'profile' : 'high'}"),
    make_pair("max_res", "max resolution: {'max_res' : '3840x2160'}"),
    make_pair("s", "video frame size: {'s' : '1920x1080'}"),
    make_pair("fps", "video fps: {'fps' : '30'}"),
    make_pair("bf", "number of b frames: {'bf' : '3'}"),
    make_pair("gop", "gop size: {'gop' : '30'}"),
    make_pair("bitrate", "bitrate: {'bitrate' : '10M'}"),
    make_pair("multipass", "multi-pass encoding: {'multipass' : 'fullres'}"),
    make_pair("ldkfs", "low-delay key frame: {'ldkfs' : ''}"),
    make_pair("maxbitrate", "max bitrate: {'maxbitrate' : '20M'}"),
    make_pair("vbvbufsize", "vbv buffer size: {'vbvbufsize' : '10M'}"),
    make_pair("vbvinit", "init vbv buffer size: {'vbvinit' : '10M'}"),
    make_pair("cq", "cq parameter: {'cq' : ''}"),
    make_pair("rc", "rc mode: {'rc' : 'cbr'}"),
    make_pair("initqp", "initial qp parameter value: {'initqp' : '32'}"),
    make_pair("qmin", "minimum qp: {'qmin' : '28'}"),
    make_pair("qmax", "maximum qp: {'qmax' : '36'}"),
    make_pair("constqp", "const qp mode: {'constqp' : ''}"),
    make_pair("temporalaq",
            "temporal adaptive quantization: {'temporalaq' : ''}"),
    make_pair("lookahead", "look ahead encoding: {'lookahead' : '8'}"),
    make_pair("aq", "adaptive quantization: {'aq' : ''}"),
    make_pair("fmt", "pixel format: {'fmt' : 'YUV444'}"),
    make_pair("idrperiod", "distance between I frames: {'idrperiod' : '256'}"),
    make_pair("numrefl0",
            "number of ref frames in l0 list: {'numrefl0' : '4'}"),
    make_pair("numrefl1",
            "number of ref frames in l1 list: {'numrefl1' : '4'}"),
    make_pair("repeatspspps",
            "enable writing of Sequence and Picture parameter for every IDR "
            "frame: {'repeatspspps' : '0'}")};
"""


class Writer(mp.Process):
    def __init__(
        self,
        queue,
        video_file_name,
        metadata_file_name,
        camera_serial,
        camera_name,
        camera_brand,
        fps,
        ffmpeg_options,
        max_video_frames=60 * 60,
        depth=False,
    ):
        super().__init__()
        self.pipe = None
        self.queue = queue
        self.video_file_name = video_file_name
        self.ffmpeg_options = ffmpeg_options
        self.metadata_file_name = metadata_file_name
        self.camera_name = camera_name
        self.camera_serial = camera_serial
        self.orig_stem = self.video_file_name.stem
        self.orig_stem_metadata = self.metadata_file_name.stem
        self.max_video_frames = max_video_frames
        self.camera_brand = camera_brand
        self.fps = fps
        self.depth = depth
        self.encFrame = np.ndarray(shape=(0), dtype=np.uint8)
        self.encFile = None
        if (camera_brand == "azure") & (depth == True):
            self.pixel_format = "gray16"
        elif (camera_brand == "lucid"):
            self.pixel_format = "gray16"
        else:
            self.pixel_format = "gray8"

        # placeholder for nv12 image
        self.img_dims = None
        self.nv12_placeholder = None

        self.initialize_metadata()

    def initialize_metadata(self):
        with open(self.metadata_file_name, "w") as metadata_f:
            metadata_writer = csv.writer(metadata_f)
            metadata_writer.writerow(
                ["frame_id", "frame_timestamp", "frame_image_uid", "queue_size"]
            )

    def run(self):
        frame_id = 0
        with open(self.metadata_file_name, "a") as metadata_f:
            metadata_writer = csv.writer(metadata_f)
            while True:
                data = self.queue.get()
                if len(data) == 0:
                    break
                else:
                    # get the computer datetime of the frame
                    frame_image_uid = str(round(time.time(), 5)).zfill(5)
                    img, camera_timestamp, current_frame = data

                    qsize = self.queue.qsize()

                    # if the frame is corrupted
                    if img is None:
                        continue
                    metadata_writer.writerow(
                        [current_frame, camera_timestamp, frame_image_uid, str(qsize)]
                    )
                    self.append(img, frame_id)

                    frame_id += 1

                    # if the current frame is greater than the max, create a new video and metadata file
                    if frame_id > self.max_video_frames:
                        self.close()
                        self.video_file_name = (
                            self.video_file_name.parent
                            / f"{self.orig_stem}.{current_frame}{self.video_file_name.suffix}"
                        )
                        logging.log(
                            logging.DEBUG, f"Creating new file self.video_file_name"
                        )
                        self.pipe = None
                        frame_id = 0

            logging.log(logging.DEBUG, f"Closing writer pipe ({self.camera_name})")
            self.close()

        logging.log(logging.DEBUG, f"Writer run finished ({self.camera_name})")

    def append(self, data, frame_id):
        # logging.log(logging.DEBUG, f"frame ({data.shape, data.dtype})")
        if self.pixel_format == "gray8":
            data = data.astype(np.uint8)
            if not self.pipe:
                encoder_dictionary = {
                    "preset": "P1",  # P1 is fastest, P7 is slowest
                    "codec": "hevc",
                    "s": f"{data.shape[1]}x{data.shape[0]}",
                    "profile": "high",  # "baseline",
                    "fps": str(int(self.fps)),
                    "multipass": "0",
                    "tuning_info": "ultra_low_latency",
                    "fmt": "YUV420",
                    # "lookahead": "1", # how far to look ahead (more is slower but better quality)
                    # "gop": "15", # larger = faster
                }
                logging.log(logging.DEBUG, f"encoder dict ({encoder_dictionary})")

                self.pipe = nvc.PyNvEncoder(
                    encoder_dictionary,
                    gpu_id=self.ffmpeg_options["gpu"],
                    format=nvc.PixelFormat.NV12,
                )
                self.encFile = open(self.video_file_name, "wb")
                logging.log(logging.DEBUG, f"Pipe created")

            # convert to nv12, which is dims X by Y*1.5
            if self.nv12_placeholder is None:
                nv12_array = grey2nv12(data)
                self.img_dims = data.shape
                self.nv12_placeholder = nv12_array
            else:
                nv12_array = self.nv12_placeholder
                nv12_array[: self.img_dims[0], : self.img_dims[1]] = data

            try:
                success = self.pipe.EncodeSingleFrame(
                    nv12_array, self.encFrame, sync=False
                )
            except Exception as e:
                success = False
                logging.log(logging.DEBUG, f"failed to create frame: {e}")

            if success:
                encByteArray = bytearray(self.encFrame)
                self.encFile.write(encByteArray)

        else:
            # write 16 bit images using ffmpeg
            self.pipe = write_frame(
                self.video_file_name,
                data,
                fps=self.fps,
                pipe=self.pipe,
                depth=self.depth,
                pixel_format=self.pixel_format,
                **self.ffmpeg_options,
            )

    def close(self):
        # indicate that no more data will be written
        # if self.pipe is not None:
        #    self.pipe.stdin.close()
        if self.pixel_format == "gray8":
            if self.encFile is not None:
                if not self.encFile.closed:
                    self.encFile.close()
        else:
            if self.pipe is not None:
                self.pipe.stdin.close()
        logging.log(logging.DEBUG, f"Writer pipe closed ({self.camera_name})")


def grey2nv12(frame):
    """Convert greyscale image to nv12"""
    # Convert grayscale to Y channel in YUV
    Y = frame.astype(np.uint8)

    # U and V channels are set to 128 (for a grayscale image, chroma channels remain constant)
    U = np.full((frame.shape[0] // 2, frame.shape[1] // 2), 128, dtype=np.uint8)
    V = np.full((frame.shape[0] // 2, frame.shape[1] // 2), 128, dtype=np.uint8)

    # Interleave U and V for NV12 format
    UV = np.empty((U.shape[0], U.shape[1] * 2), dtype=np.uint8)
    UV[:, 0::2] = U
    UV[:, 1::2] = V

    # Stack Y and UV to create the NV12 format
    nv12 = np.vstack((Y, UV))

    return nv12
