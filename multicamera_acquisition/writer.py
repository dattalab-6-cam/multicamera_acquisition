
import csv
import logging
import multiprocessing as mp
import subprocess
import time

import numpy as np
import PyNvCodec as nvc

from multicamera_acquisition.config.default_nvc_writer_config import (
    default_nvc_writer_config
)
from multicamera_acquisition.config.default_ffmpeg_writer_config import (
    default_ffmpeg_writer_config,
)

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


class BaseWriter(mp.Process):

    def __init__(self, queue, video_file_name, metadata_file_name, config=None):
        super().__init__()

        # Store params
        self.queue = queue
        self.video_file_name = video_file_name
        self.metadata_file_name = metadata_file_name
        self.config = config

        # File naming stuff
        self.orig_stem = self.video_file_name.stem
        self.orig_stem_metadata = self.metadata_file_name.stem

        # Create the metadata file
        self.initialize_metadata()

        # Set up the config
        if config is None:
            self.config = self.default_writer_config()
        else:
            self.validate_config()

        # Set pipe to be none initially
        self.pipe = None

        # Initialize frame counter
        self.frame_id = 0

    def initialize_metadata(self):
        with open(self.metadata_file_name, "w") as metadata_f:
            metadata_writer = csv.writer(metadata_f)
            metadata_writer.writerow(
                ["frame_id", "frame_timestamp", "frame_image_uid", "queue_size"]
            )

    def _get_new_pipe(self, data_shape):
        pass

    def run(self):

        # Open metadata file for writing
        with open(self.metadata_file_name, "a") as metadata_f:
            metadata_writer = csv.writer(metadata_f)

            # Loop until we get a stop signal
            while True:

                # Get data from the queue
                data = self.queue.get()

                # If we get an empty tuple, stop
                if len(data) == 0:
                    break

                # Unpack the data
                img, camera_timestamp, current_frame = data

                # Get the metadata about the frame
                frame_image_uid = str(round(time.time(), 5)).zfill(5)
                try:
                    qsize = self.queue.qsize()
                except NotImplementedError:
                    qsize = np.nan

                # If the frame is corrupted (TODO: how does this check for corruption?)
                if img is None:
                    continue

                # Write the metadata
                metadata_writer.writerow(
                    [current_frame, camera_timestamp, frame_image_uid, str(qsize)]
                )

                # Reset the pipe if needed
                if self.pipe is None:
                    data_shape = img.shape
                    self._get_new_pipe(data_shape)

                # Write the frame
                self.append(img)

                # Increment the frame counter
                self.frame_id = self.frame_id + 1
                self.new_debug_attr = "HELLO"

                # If the current frame is greater than the max, create a new video and metadata file
                if self.frame_id > self.config["max_video_frames"]:
                    self._reset_writer(current_frame)

            logging.log(logging.DEBUG, f"Closing writer pipe ({self.config['camera_name']})")
            self.close()


        logging.log(logging.DEBUG, f"Writer run finished ({self.config['camera_name']})")

    def _reset_writer(self, current_frame):
        self.close()
        self.frame_id = 0
        self.video_file_name = (
            self.video_file_name.parent
            / f"{self.orig_stem}.{current_frame}{self.video_file_name.suffix}"
        )

    def append(self, data):
        pass

    def close(self):
        pass

# TODO: deal with ffmpeg warning:
    # "Timestamps are unset in a packet for stream 0. This is deprecated and will stop working in the future. Fix your code to set the timestamps properly"
class NVC_Writer(BaseWriter):

    def __init__(self, queue, video_file_name, metadata_file_name, config=None):
        super().__init__(queue=queue, video_file_name=video_file_name, metadata_file_name=metadata_file_name, config=config)

        # VPF-specific stuff
        self.encFrame = np.ndarray(shape=(0), dtype=np.uint8)
        self.encFile = None
        self.img_dims = None  
        self.nv12_placeholder = None  # placeholder for nv12 image 
        self.frames_flushed = 0

    @staticmethod
    def default_writer_config():
        return default_nvc_writer_config()

    def validate_config(self):

        # Check pixel format (only gray8 supported by VPF)
        assert "pixel_format" in self.config, "VPF requires pixel_format to be specified"
        assert self.config["pixel_format"] == "gray8", "VPF only supports gray8 pixel format"

    def _get_new_pipe(self, data_shape):
        encoder_dictionary = {
            "preset": self.config["preset"],  # P1 is fastest, P7 is slowest
            "codec": self.config["codec"],  # "hevc",
            "s": f"{data_shape[1]}x{data_shape[0]}",
            "profile": self.config["profile"],
            "fps": str(int(self.config["fps"])),
            "multipass": self.config["multipass"],  # "fullres",  # "0",
            "tuning_info": self.config["tuning_info"],
            "fmt": self.config["fmt"],
            # "lookahead": "1", # how far to look ahead (more is slower but better quality)
            # "gop": "15", # larger = faster
        }
        logging.log(logging.DEBUG, f"encoder dict ({encoder_dictionary})")
        self.pipe = nvc.PyNvEncoder(
            encoder_dictionary,
            gpu_id=self.config["gpu"],
            format=nvc.PixelFormat.NV12,
        )
        self.encFile = open(self.video_file_name, "xb")
        logging.log(logging.DEBUG, "Pipe created")

    def append(self, data):

        # Cast to uint8
        data = data.astype(np.uint8)

        # Convert to nv12, which is dims X by Y*1.5
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

    def _wait_to_finish(self):
        
        # Encoder is asynchronous, so we need to flush it
        while True:
            success = self.pipe.FlushSinglePacket(self.encFrame)
            if success:
                encByteArray = bytearray(self.encFrame)
                self.encFile.write(encByteArray)
                self.frames_flushed += 1
            else:
                break

    def _mux_video(self):
        """
        In some prelim tests on O2 on other videos, this kind of muxing runs at
        about 100x, so it should be ok to run for one-hour-long videos.
        """
        # use an ffmpeg subprocess command to mux the video
        # format: ffmpeg -i "output.h264" -c:v copy -f mp4 "output.mp4"
        command = [
            "ffmpeg",
            '-y',
            "-i",
            str(self.video_file_name),
            "-c:v",
            "copy",
            "-f",
            "mp4",
            str(self.video_file_name).replace(".mp4", ".muxed.mp4"),  # TODO: clean this up
        ]
        self._mux_pipe = subprocess.Popen(command)

        # wait for the muxing to finish
        self._mux_pipe.wait()

    def close(self):
        if self.pipe is not None:
            self._wait_to_finish()

        if self.encFile is not None:
            if not self.encFile.closed:
                self.encFile.close()
        self.pipe = None

        # mux the video
        self._mux_video()


class FFMPEG_Writer(BaseWriter):
    def __init__(self, queue, video_file_name, metadata_file_name, config=None):
        super().__init__(queue=queue, video_file_name=video_file_name, metadata_file_name=metadata_file_name, config=config)

        # FFMPEG-specific stuff
        pass

        # Read in the config
        self.validate_config()

    @staticmethod
    def default_writer_config():
        return default_ffmpeg_writer_config()

    def validate_config(self):
        # Check pixel format
        assert "pixel_format" in self.config, "pixel_format msut be specified"    

    def append(self, data):

        # Convert to the correct data format
        if self.config["pixel_format"] == "gray8":
            data = data.astype(np.uint8)
        elif self.config["pixel_format"] == "gray16":
            data = data.astype(np.uint16)

        # Write it to the pipe
        self.pipe.stdin.write(data.tobytes())

    def _get_new_pipe(self, data_shape):

        # Generate the ffmpeg command
        command = FFMPEG_Writer.create_ffmpeg_pipe_command(
            self.video_file_name,
            data_shape,
            self.config["fps"],
            quality=self.config["quality"],
            pixel_format=self.config["pixel_format"],
            gpu=self.config["gpu"],
            depth=self.config["depth"],
            loglevel=self.config["loglevel"],
        )

        # Print it
        print(' '.join(command))

        # Create a subprocess pipe to write frames
        with (
            open(f"{str(self.video_file_name)}.stdout.txt", "w") as f_out,
            open(f"{str(self.video_file_name)}.stderr.txt", "w") as f_err,
        ):
            self.pipe = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=f_out,  # standard output is redirected to 'stdout.txt'
                stderr=f_err,  # standard error is redirected to 'stderr.txt'
            )

    def close(self):
        if self.pipe is not None:
            self.pipe.stdin.close()
        self.pipe = None

    @staticmethod
    def create_ffmpeg_pipe_command(
        filename,
        frame_shape,
        fps,
        quality=15,
        pixel_format="gray8",
        gpu=None,
        depth=False,
        loglevel="error",
    ):
        """Create a pipe for ffmpeg"""
        # Get the size of the frame
        frame_size = "{0:d}x{1:d}".format(frame_shape[1], frame_shape[0])
        logging.log(logging.DEBUG, f"FRAME SHAPE {frame_shape}")
        if not depth:
            # Prepare the basic ffmpeg command
            command = [
                "ffmpeg",
                "-loglevel",
                loglevel,
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
