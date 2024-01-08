def default_azure_config():
    """A default config dict for an Azure Kinect camera."""
    # also to include: name, sn, model, firmware, acq mode (eg nfov unbinned)
    config = {
        "fps": 30,
        "depth_mode": "NFOV_UNBINNED",  # "narrow field of view, unbinned"
        "synchronized_images_only": False,
        "sync_mode": "subordinate",
        "subordinate_delay_off_master_usec": 500,
    }
    return config
