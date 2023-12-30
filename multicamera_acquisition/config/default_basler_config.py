

def default_basler_config():
    """A default config dict for a Basler camera.
    """
    config = {
        # 'name': 'Basler acA2440-75uc (22400108)',
        # 'serial_number': '22400108',
        # 'model': 'acA2440-75uc',
        # 'vendor': 'Basler',
        # 'interface': 'USB3',
        # 'sensor': 'IMX250',
        # 'resolution': (1936, 1216),
        'fps': 30,
        'roi': None,  # ie use the entire roi
        'gain': 6,
        'exposure': 1000,
        # 'readout_mode': 'Normal',  # options are 'Fast' and 'Normal'. 'Fast' is required for >160 fps but might lead to lower image quality.
        'trigger': {
            'short_name': 'arduino',
            'acquisition_mode': 'Continuous',
            'trigger_source': 'Line2',
            'trigger_selector': 'FrameStart',
            'trigger_activation': 'RisingEdge'
        }
    }
    return config
