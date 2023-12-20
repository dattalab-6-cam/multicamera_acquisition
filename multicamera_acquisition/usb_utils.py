import usb.core


def reset_usb(
    products=[
        "a2A1920-160umBAS",
        "Azure Kinect 4K Camera",
        "Azure Kinect Depth Camera",
        "Azure Kinect Microphone Array",
    ],
    verbose=False,
):
    devs = usb.core.find(find_all=True)

    # Iterate over the devices and save their details if the manufacturer is 'Basler'
    for dev in devs:
        try:
            product = dev.product
            serial_number = dev.serial_number  # Get the serial number
        except Exception as e:
            if verbose:
                print(f"Error retrieving product info or serial number: {e}")
            continue

        if product in products:
            try:
                if verbose:
                    print(
                        f"resetting {product} ({hex(dev.idVendor)}, {hex(dev.idProduct)}) with Serial Number: {serial_number}"
                    )
                dev.reset()
            except Exception as e:
                print(f"Error resetting device: {product}. Error: {e}")
