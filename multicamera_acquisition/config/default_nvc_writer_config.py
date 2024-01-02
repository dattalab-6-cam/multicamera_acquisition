
def default_nvc_writer_config(fps, vid_type="ir"):
    """Generate a valid config for an NVC Writer.
    """
    config = {
        'fps': fps,
        'max_video_frames': 60 * 60 * fps * 24,  # one day
    }

    if vid_type == "ir":
        config['pixel_format'] = 'gray8'
    elif vid_type == "depth":
        config['pixel_format'] = 'gray16'
    
    return config