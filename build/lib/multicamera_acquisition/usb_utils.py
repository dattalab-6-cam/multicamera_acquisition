import usb.core

import usb.core


def reset_usb(venders = ['Basler', 'Flir'], verbose=False):
    # Find all USB devices
    devs = usb.core.find(find_all=True)

    basler_devices = []

    # Iterate over the devices and save their details if the manufacturer is 'Basler'
    for dev in devs:
        try:
            manufacturer = usb.util.get_string(dev, dev.iManufacturer)
            if manufacturer in venders:
                basler_devices.append((hex(dev.idVendor), hex(dev.idProduct)))
                dev.reset()
        except Exception as e:
            if verbose:
                print(f"Error retrieving manufacturer for device: {dev}")
                print(f"Error: {e}")
            