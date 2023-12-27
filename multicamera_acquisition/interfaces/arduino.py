import struct
import numpy
import warnings
import sys
import glob
import serial
import logging

def packIntAsLong(value):
    """Packs a python 4 byte integer to an arduino long
    Parameters
    ----------
    value : int
        A 4 byte integer
    Returns
    -------
    packed : bytes
        A 4 byte long
    """
    return struct.pack("i", value)


def wait_for_serial_confirmation(
    arduino, expected_confirmation, seconds_to_wait=5, timeout_duration_s=0.1
):
    confirmation = None
    for i in range(int(seconds_to_wait / timeout_duration_s)):
        confirmation = arduino.readline().decode("utf-8").strip("\r\n")
        if confirmation == expected_confirmation:
            logging.info("Confirmation recieved: {}".format(confirmation))
            break
        else:
            if len(confirmation) > 0:
                logging.info(
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


def find_serial_ports():
    """ Lists serial port names, across OS's.
    https://stackoverflow.com/questions/12090503/listing-available-com-ports-with-python

        :raises EnvironmentError:
            On unsupported or unknown platforms
        :returns:
            A list of the serial ports available on the system
    """
    if sys.platform.startswith('win'):
        ports = ['COM%s' % (i + 1) for i in range(256)]
    elif sys.platform.startswith('linux') or sys.platform.startswith('cygwin'):
        # this excludes your current terminal "/dev/tty"
        ports = glob.glob('/dev/tty[A-Za-z]*')
    elif sys.platform.startswith('darwin'):
        ports = glob.glob('/dev/tty.*')
    else:
        raise EnvironmentError('Unsupported platform')

    result = []
    for port in ports:
        try:
            s = serial.Serial(port)
            s.close()
            result.append(port)
        except (OSError, serial.SerialException):
            pass
    return result