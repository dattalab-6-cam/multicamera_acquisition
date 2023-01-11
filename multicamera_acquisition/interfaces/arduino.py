import struct
import numpy
import warnings

def packIntAsLong(value):
    '''Packs a python 4 byte integer to an arduino long
    Parameters
    ----------
    value : int
        A 4 byte integer
    Returns
    -------
    packed : bytes
        A 4 byte long
    '''
    return struct.pack("i", value)


def wait_for_serial_confirmation(
    arduino,
    expected_confirmation, 
    recording_duration=5, 
    timeout_duration_s=0.1
):
    confirmation = None
    for i in tqdm(
        range(int(recording_duration / timeout_duration_s)),
        desc="Waiting for {} confirmation".format(expected_confirmation),
    ):
        confirmation = arduino.readline().decode("utf-8").strip("\r\n")
        if confirmation == expected_confirmation:
            print("Confirmation recieved: {}".format(confirmation))
            break
        else:
            if len(confirmation) > 0:
                warnings.warn(
                    'PySerial: "{}" confirmation expected, got "{}"". Trying again.'.format(
                        expected_confirmation, confirmation
                    )
                )
    if confirmation != expected_confirmation:
        raise ValueError(
            'Confirmation "{}" signal never recieved from Arduino'.format(
                expected_confirmation
            )
        )
    return confirmation