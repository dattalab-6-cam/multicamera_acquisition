

def default_basler_config():
    """A default config dict for a Basler camera.
    """
    config = {
        'fps': 30,
        'roi': None,  # ie use the entire roi
        'gain': 6,
        'exposure': 1000,
        'trigger': {
            'short_name': 'arduino',
            'acquisition_mode': 'Continuous',
            'trigger_source': 'Line2',
            'trigger_selector': 'FrameStart',
            'trigger_activation': 'RisingEdge'
        }
    }
    return config
