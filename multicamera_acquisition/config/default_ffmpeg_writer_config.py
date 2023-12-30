
def default_ffmpeg_writer_config(vid_type="ir", gpu=None):
    """A default config dict for an ffmpeg writer.

    Frame size tbd on the fly.
    """
    config = {
        'fps': 30,
        'max_video_frames': 60 * 60 * 30,  # one hour at 30 fps
        'quality': 15,
        'loglevel': 'error',
    }

    if vid_type == "ir":
        config['pixel_format'] = 'grey8'
        config['output_px_format'] = 'yuv420p'  # Output pixel format
        if gpu is not None:
            config['video_codec'] = 'h264_nvenc'
            config['gpu'] = gpu
            config['preset'] = 'p1'  # p1 - p7, p1 is fastest, p7 is slowest
        else:
            config['video_codec'] = 'libx264'
            config['preset'] = 'ultrafast'

    elif vid_type == "depth":
        config['pixel_format'] = 'grey16'
        config['video_codec'] = 'ffv1'  # lossless depth    

    return config
