import csv
import logging
import multiprocessing as mp
import subprocess
import time
import warnings
import os
from pathlib import Path
import traceback

import numpy as np

from multicamera_acquisition.logging_utils import setup_child_logger


class BaseWriter(mp.Process):
    def __init__(self, queue, video_file_name, metadata_file_name, config=None, process_name=None,
        logger_queue=None,
        logging_level=logging.DEBUG, fps=None):
        """An abstract parent class to write videos from a queue.

        Parameters
        ----------
        queue : multiprocessing.Queue
            A multiprocessing queue from which to read frames.

        video_file_name : str or Path
            The name of the video file to write.

        metadata_file_name : str or Path
            The name of the metadata file to write.

        config : dict
            A dictionary of configuration parameters for the writer.
            If None, a default config will be used.
            As of now, should contain fps.  #TODO: make fps a passable kwarg that can come from a global config param like for the cameras

        fps : int
            The frames per second of the video.
        """
        super().__init__(name=process_name)

        # Store params
        self.queue = queue
        self.video_file_name = video_file_name
        self.metadata_file_name = metadata_file_name
        self.config = config
        self.logger_queue = logger_queue
        self.logging_level = logging_level

        # File naming stuff
        # File name format is {prefix}.{start_timestamp}.{camera_name}.{serial_num}.{first_frame_number}.{extension}
        # and metadata is {full_filename.stem}.metadata.csv.

        # We want the stem to be everything up to the first frame number,
        # so that we can start new videos with the same stem + new frame number.
        self.orig_stem = ".".join(self.video_file_name.stem.split(".")[:-1])

        # Check user has passed at least an fps
        if config is None and fps is None:
            raise ValueError("At least fps must be specified, even if config is None.")

        # Set up the config
        if config is None:
            self.config = self.default_writer_config(fps).copy()
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
        self.metadata_file = open(self.metadata_file_name, "a", newline='')
        self.metadata_writer = csv.writer(self.metadata_file)

    def _get_new_pipe(self, data_shape):
        pass

    def run(self):

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
            raise ValueError(
                "logger_queue must be a multiprocessing.Queue or None."
            )

        # Get CSV writer for metadata file
        self.logger.debug("Creating metadata file")
        self.initialize_metadata()

        # Loop until we get a stop signal
        try:
            while True:
                # Get data from the queue
                data = self.queue.get()

                # If we get an empty tuple, stop
                if len(data) == 0:
                    self.logger.debug("Got stop signal")
                    break

                # Unpack the data
                # TODO: if we drop a frame, is current_frame still valid?
                img, camera_timestamp, current_frame = data

                # Get the metadata about the frame
                frame_image_uid = str(round(time.time(), 5)).zfill(5)
                try:
                    qsize = self.queue.qsize()
                except NotImplementedError:
                    qsize = np.nan

                # If the frame is corrupted (TODO: how does this check for corruption?)
                if img is None:
                    self.logger.warning("Got empty frame (corruption?), continuing")
                    continue

                # Write the metadata
                try:
                    self.metadata_writer.writerow(
                        [current_frame, camera_timestamp, frame_image_uid, str(qsize)]
                    )
                except ValueError as e:
                    self.logger.error(
                        f"Failed to write metadata for frame {current_frame}, frame id: {self.frame_id}"
                    )
                    self.logger.error(e)
                    raise

                # Reset the pipe if needed (at beginning, or after self._reset_writer())
                if self.pipe is None:
                    data_shape = img.shape
                    self._get_new_pipe(data_shape)
                    self.logger.debug("Created new video pipe")

                # Write the frame
                self.append(img)

                # Increment the frame counter
                self.frame_id = self.frame_id + 1

                # If the current frame is greater than the max, create a new video and metadata file
                if self.frame_id >= self.config["max_video_frames"]:
                    self.logger.info("Reached max vid frames, resetting writers")
                    self._reset_writers()
        except Exception as e:
            self.logger.error(traceback.format_exc())
            raise e

        self.logger.debug(f"Closing writer pipe ({self.config['camera_name']})")
        self.close_video()

        self.logger.debug(f"Writer run finished ({self.config['camera_name']})")
        self.finish()

    def _reset_writers(self):
        # Reset the video writer
        self.close_video()
        self.video_file_name = (
            self.video_file_name.parent
            / f"{self.orig_stem}.{self.frame_id}{self.video_file_name.suffix}"  # nb: no dot before suffix because it's already there
        )
        
        # [new pipe will be created on next frame]

        # Reset the metadata writer
        self.metadata_file.close()
        self.metadata_file_name = (
            self.metadata_file_name.parent
            / f"{self.orig_stem}.{self.frame_id}.metadata.csv"
        )
        self.initialize_metadata()

        # Reset the frame id counter
        self.frame_id = 0

    def append(self, data):
        pass

    def close_video(self):
        pass

    def finish(self):
        pass


class NVC_Writer(BaseWriter):
    def __init__(
        self, 
        queue, 
        video_file_name, 
        metadata_file_name, 
        config=None, 
        process_name=None,
        logger_queue=None,
        logging_level=logging.DEBUG,
    ):

        super().__init__(
            queue=queue,
            video_file_name=video_file_name,
            metadata_file_name=metadata_file_name,
            config=config,
            process_name=process_name,
            logger_queue=logger_queue,
            logging_level=logging_level,
        )

        # VPF-specific stuff
        self.encFrame = np.ndarray(shape=(0), dtype=np.uint8)
        self.encFile = None
        self.img_dims = None
        self.nv12_placeholder = None  # placeholder for nv12 image
        self.frames_flushed = 0

    @staticmethod
    def default_writer_config(fps, gpu=0):
        """Generate a valid config for an NVC Writer."""
        if gpu is None:
            raise ValueError("GPU must be specified for NVC writer")
        config = {
            # pipeline params
            "fps": fps,
            "type": "nvc",
            "max_video_frames": 60 * 60 * fps * 24,  # one day
            "auto_remux_videos": True,
            # encoder params
            "pixel_format": "gray8",
            "preset": "P1",  # P1 fastest, P7 slowest / x = set(('apple', 'banana', 'cherry'))
            "codec": "h264",  # h264, hevc
            "profile": "high",  # high or baseline (?)
            "multipass": "0",  # "0", "fullres"
            "tuning_info": "ultra_low_latency",
            "fmt": "YUV420",
            "gpu": gpu,
            # additional params from CW
            "idrperiod": "256",
            "gop": "30",
        }

        return config

    def validate_config(self):
        # Check pixel format (only gray8 supported by VPF)
        assert (
            "pixel_format" in self.config
        ), "VPF requires pixel_format to be specified"
        assert (
            self.config["pixel_format"] == "gray8"
        ), "VPF only supports gray8 pixel format"

    def _get_new_pipe(self, data_shape):
        import PyNvCodec as nvc

        # TODO: make part of the config be exactly the dictionary that is passed to the encoder,
        # so that we can pass in arbitrary params.
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
            "idrperiod": self.config["idrperiod"],  # "256", # distance between I frames
            "gop": self.config["gop"],  # larger = faster
        }
        self.logger.debug(f"encoder dict ({encoder_dictionary}")
        self.pipe = nvc.PyNvEncoder(
            encoder_dictionary,
            gpu_id=self.config["gpu"],
            format=nvc.PixelFormat.NV12,
        )
        self.encFile = open(self.video_file_name, "wb")
        self._current_vid_muxing = False
        self.logger.debug("Pipe created")

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
            success = self.pipe.EncodeSingleFrame(nv12_array, self.encFrame, sync=False)
        except Exception as e:
            success = False
            self.logger.debug(f"failed to create frame: {e}")

        if success:
            encByteArray = bytearray(self.encFrame)
            self.encFile.write(encByteArray)

    def close_video(self):
        # Flush the PyNvCodec encoder
        if self.pipe is not None:
            self.flush_enc_stream()

        # Close the video file
        if self.encFile is not None:
            if not self.encFile.closed:
                self.encFile.close()

        # Reset the pipe to None so that it can be reinitialized
        self.pipe = None

        # Set the video to be muxed if requested
        if self.config["auto_remux_videos"] and not self._current_vid_muxing:
            self._mux_video(self.video_file_name)

    def flush_enc_stream(self):
        # Encoder is asynchronous, so we need to flush it
        while True:
            success = self.pipe.FlushSinglePacket(self.encFrame)
            if success:
                encByteArray = bytearray(self.encFrame)
                self.encFile.write(encByteArray)
                self.frames_flushed += 1
            else:
                break

    def _mux_video(self, video_file_name):

        # Create a muxer process
        self.logger.debug(f"Creating muxer process for {video_file_name}")
        success_event = mp.Event()
        muxer = VideoMuxer(video_file_name, success_event)

        # Start the muxer process
        muxer.start()

        # Save the muxer process to be joined when the parent ends
        if not hasattr(self, "muxer_processes"):
            self.muxer_processes = []
        if not hasattr(self, "vids_muxed"):
            self.vids_muxed = []
        self.muxer_processes.append(muxer)
        self.vids_muxed.append(video_file_name)
        self._current_vid_muxing = True

    def finish(self):

        # Join the muxer processes and rename the videos
        if self.config["auto_remux_videos"] and hasattr(self, "muxer_processes"):
            self.logger.debug("Joining muxer processes")
            for vid, muxer in zip(self.vids_muxed, self.muxer_processes):
                muxer.join()
                if not muxer.success.is_set():
                    warnings.warn(f"Failed to mux {muxer.video_file_name}")
                else:
                    # Rename the muxed video
                    os.remove(vid)
                    muxed_video_file_name = vid.parent / f"{vid.stem}.muxed.mp4"
                    os.rename(muxed_video_file_name, vid)


class VideoMuxer(mp.Process):
    def __init__(self, target_file, success_event):
        super().__init__()
        if not isinstance(target_file, Path):
            target_file = Path(target_file)
        self.skip = False
        self.success = success_event
        self.video_file_name = target_file
        self._validate_target_file()

    def _validate_target_file(self):
        if self.video_file_name.suffix != ".mp4":
            warnings.warn("VideoMuxer only works on .mp4 files — skipping")
            self.skip = True

        if not self.video_file_name.exists():
            warnings.warn(
                f"VideoMuxer target file {self.video_file_name} does not exist"
            )
            self.skip = True

    def run(self):
        """
        In some prelim tests on O2 on other videos, this kind of muxing runs at
        about 100x, so it should be ok to run for one-hour-long videos.
        TODO:  make it a flag that can be ignored and also make sure it handles multiple videos for each camera elegantly
        Ie the code right now allows you to create new videos every n frames so there will be 4 5 min vids instead of 1 20min
        """

        # Exit early if there's an issue detected
        if self.skip:
            return

        # ffmpeg can't operate in place, so we need to make a tmp file name for the muxed video
        # and then delete the origin + rename the muxed one
        tmp_file_name = (
            self.video_file_name.parent / f"{self.video_file_name.stem}.muxed.mp4"
        )

        # Generate an ffmpeg subprocess command to mux the video
        command = [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",  # suppress ffmpeg output
            "-i",
            str(self.video_file_name),
            "-c:v",
            "copy",
            "-f",
            "mp4",
            str(tmp_file_name),
        ]

        # Run the muxing once the video is ready (ie released by the writer)
        self._mux_pipe = subprocess.Popen(command)

        # Wait for the muxing to finish
        self._mux_pipe.wait()

        # NB: don't try to delete / rename the files here, it throws weird permission errors.

        # TODO: check exit code of subproc, if error, dont delete the original file
        # Declare success!
        self.success.set()


# TODO: deal with ffmpeg warning:
# "Timestamps are unset in a packet for stream 0. This is deprecated and will stop working in the future. Fix your code to set the timestamps properly"
class FFMPEG_Writer(BaseWriter):
    def __init__(
        self, 
        queue, 
        video_file_name, 
        metadata_file_name, 
        config=None, 
        process_name=None,
        logger_queue=None,
        logging_level=logging.DEBUG,
    ):

        super().__init__(
            queue=queue,
            video_file_name=video_file_name,
            metadata_file_name=metadata_file_name,
            config=config,
            process_name=process_name,
            logger_queue=logger_queue,
            logging_level=logging_level,
        )

        # FFMPEG-specific stuff
        pass

        # Read in the config
        self.validate_config()

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

        # Create a subprocess pipe to write frames
        # TODO: give user option to save ffmpeg logs to an output file.
        # Having trouble getting them to write directly to the mp logger.
        self.pipe = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
        )

    def close_video(self):
        if self.pipe is not None:
            self.pipe.stdin.close()
        self.pipe = None

    @staticmethod
    def default_writer_config(fps, vid_type="ir", gpu=None):
        """A default config dict for an ffmpeg writer.

        Frame size tbd on the fly.
        """
        config = {
            "fps": fps,
            "max_video_frames": 60 * 60 * fps * 24,  # one day  # TODO: do we really want to hardcode this?
            "quality": 15,
            "loglevel": "error",
            "type": "ffmpeg",
        }

        if vid_type == "ir":
            # Use uint8 for ir vids
            config["pixel_format"] = "gray8"

            # Use a pixel format that is readable by most players
            config["output_px_format"] = "yuv420p"  # Output pixel format

            # Set codec and preset depending on whether we have a gpu
            if gpu is not None:
                config["video_codec"] = "h264_nvenc"
                config["gpu"] = gpu
                config["preset"] = "p1"  # p1 - p7, p1 is fastest, p7 is slowest
            else:
                config["video_codec"] = "libx264"
                config["preset"] = "ultrafast"
                config["gpu"] = None

            config["depth"] = False

        elif vid_type == "depth":
            # Use uint16 for depth vids
            config["pixel_format"] = "gray16"
            config["video_codec"] = "ffv1"  # lossless depth
            config["depth"] = True
            config["gpu"] = None

        return config

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
                if pixel_format in ["gray16", "gray16"]:
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

            if pixel_format not in ["gray16", "gray16"]:
                command += ["-pix_fmt", "yuv420p"]  # Output pixel format

            # Additional options for output format and filename
            command += [str(filename)]  # Output filename
        else:
            codec = "ffv1"
            command = [
                "ffmpeg",
                "-loglevel",
                loglevel,
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

        return command


def get_writer(
    queue, 
    video_file_name, 
    metadata_file_name, 
    writer_type="nvc", 
    config=None,
    process_name=None,
    logger_queue=None,
    logging_level=logging.DEBUG,
):
    """Get a Writer object."""
    if writer_type == "nvc":
        writer = NVC_Writer(
            queue, video_file_name, metadata_file_name, config=config, process_name=process_name, logger_queue=logger_queue, logging_level=logging_level
        )
    elif writer_type == "ffmpeg":
        writer = FFMPEG_Writer(
            queue, video_file_name, metadata_file_name, config=config, process_name=process_name, logger_queue=logger_queue, logging_level=logging_level
        )
    else:
        raise ValueError(f"Unrecognized writer type: {writer_type}")
    return writer


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
