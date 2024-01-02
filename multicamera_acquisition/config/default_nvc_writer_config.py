
def default_nvc_writer_config(fps):
    """Generate a valid config for an NVC Writer.
    """
    config = {
        'fps': fps,
        'max_video_frames': 60 * 60 * fps * 24,  # one day
        'pixel_format': 'gray8',
        "preset": "P1",  # P1 fastest, P7 slowest / x = set(('apple', 'banana', 'cherry'))
        "codec": "h264",  # h264, hevc
        "profile": "high",  # high or baseline (?)
        "multipass": "0",  # "0", "fullres"
        "tuning_info": "ultra_low_latency",
        "fmt": "YUV420",
        # "lookahead": "1", # how far to look ahead (more is slower but better quality)
        # "gop": "15", # larger = faster
    }
    
    return config