import os
import time
import numpy as np

from multicamera_acquisition.interfaces.microcontroller import Microcontroller


def test_microcontroller():
    """
    Test requires that the computer is connected to a microcontroller with the correct firmware.
    """
    recording_duration_s = 2
    basename = "./multicamera_acquisition/scratch/mcu_test/mcu_test"

    microcontroller = Microcontroller(basename=basename)
    microcontroller.open_serial_connection()
    microcontroller.start_acquisition(recording_duration_s)

    finished = False
    start_time = time.time()
    while time.time() < start_time + recording_duration_s + 1:
        finished = microcontroller.check_for_input()
        if finished:
            break
    microcontroller.close()

    assert finished, "Microcontroller did not finish acquisition."
    assert os.path.exists(basename + ".triggerdata.csv"), "No trigger data file found."
