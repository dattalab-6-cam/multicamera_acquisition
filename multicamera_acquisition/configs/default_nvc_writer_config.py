
def default_nvc_writer_config(vid_type="ir"):
    """A default config dict for an NVC writer.
    """
    config = {
        'fps': 30,
        'max_video_frames': 60 * 60 * 30,  # one hour at 30 fps
    }

    if vid_type == "ir":
        config['pixel_format'] = 'gray8'
    elif vid_type == "depth":
        config['pixel_format'] = 'gray16'
    
    return config