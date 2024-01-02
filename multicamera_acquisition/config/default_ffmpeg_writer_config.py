
def default_ffmpeg_writer_config(fps, vid_type="ir", gpu=None):
    """A default config dict for an ffmpeg writer.

    Frame size tbd on the fly.
    """
    config = {
        'fps': fps,
        'max_video_frames': 60 * 60 * fps * 24,  # one day
        'quality': 15,
        'loglevel': 'error',
    }

    if vid_type == "ir":

        # Use uint8 for ir vids
        config['pixel_format'] = 'gray8'

        # Use a pixel format that is readable by most players
        config['output_px_format'] = 'yuv420p'  # Output pixel format

        # Set codec and preset depending on whether we have a gpu
        if gpu is not None:
            config['video_codec'] = 'h264_nvenc'
            config['gpu'] = gpu
            config['preset'] = 'p1'  # p1 - p7, p1 is fastest, p7 is slowest
        else:
            config['video_codec'] = 'libx264'
            config['preset'] = 'ultrafast'
            config["gpu"] = None

        config["depth"] = False

    elif vid_type == "depth":

        # Use uint16 for depth vids
        config['pixel_format'] = 'grey16'
        config['video_codec'] = 'ffv1'  # lossless depth    
        config['depth'] = True
        config['gpu'] = None

    return config
