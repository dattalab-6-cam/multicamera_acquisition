# Testing with pytest

In order to ensure that new changes do not break our code, we have developed a suite of tests. Running the tests is straightforward from the command line with pytest.


## Installation
If you don't already have it, run `pip install pytest`. You can check by running `pyest --help`.


## Tests to run before pushing to `main`
In lieu of setting up CI, we require the following tests to pass before pushing to main:
* On any computer: `pytest ./multicamera_acquisition/tests`
* On a 6 cam rig with cameras and an MCU: `pytest ./multicamera_acquisition/tests --camera_type basler_camera --runall`
* On a 6 cam rig: run an acquisition notebook with a config that was previously known to work. If updates to the config are required, document them all and post the required changes in the PR for discussion.

## Running tests
There are many optional flags available to set how pytest behaves, described here. See below for some examples of full commands to run.

### Flags for switching test behavior

The code relies heavily on external hardware — Basler and Azure cameras, microcontrollers, lights, etc. We have taken great pains to ensure that (at least some of) the code is testable without actually having access to this external hardware. This is accomplished by running an emulated version of the Basler camera. Currently, we cannot emulate the Azure or the microcontroller. As a consequence of this, there are options in the test suite to use either the emulated or real Basler cameras.

* **Basler real vs. emulated cameras**: `camera_type`: either `basler_emulated` (default) or `basler_camera`. If `basler_emulated`, will run as many tests as possible with an emulated version of the camera. Otherwise, looks for real cameras.

The code relies on NVIDIA's VPF, but this isn't always installed on dev computers (ie Macs). So to facilitate testing the Writer's on Mac's (and also as a back-up option in general), we have ffmpeg as an option.
* **NVC vs. ffmpeg**: `writer_type`: either `nvc` (default) or `ffmpeg`.


Testing code with subprocesses is a bit difficult, as subprocess output is not always shown to the user. There is a pytest flag to help with this:

* **Printing errors from sub-processes**: pytest has a built-in option, `-s`, that will print all output from the code to the command line. Use this flag to enable printing of error tracebacks from subprocesses, otherwise they will fail silently.

### Flags for enabling tests
* The GUI tests are somewhat slow, so there is a separate flag to enable those tests: `--rungui` (e.g. `pytest --rungui`)
* The pyk4a library is not installable on Mac, where many of us do development. So there is a separate flag to enable pyk4a tests, `--runpyk4a' (e.g. `pytest --runpyk4a`).
* There is a separate flag to enable microcontroller tests, `--runmcu' (e.g. `pytest --runmcu`).
* Finally, there is a `--runall` flag that will behave as if all three above flags were passed.

## Example pytest invocations
* To run core development tests (emulated Baslers, no gui, no mcu): `pytest ./multicamera_acquisition/tests`
  * To run the same with real cameras on a rig computer: `pytest ./multicamera_acquisition/tests --camera_type basler_camera`
  * To run the same with the fallback ffmpeg writer: `pytest ./multicamera_acquisition/tests --camera_type basler_camera --writer_type ffmpeg`
* To include the gui tests: `pytest ./multicamera_acquisition/tests --rungui`
* To include the mcu tests: `pytest ./multicamera_acquisition/tests --runmcu`
* To run all tests: `pytest ./multicamera_acquisition/tests --runall`

* You can also pass a specific file directly to pytest: `pytest ./multicamera_acquisition/tests/interfaces/test_azures.py`
* Or even a specific function: `pytest ./multicamera_acquisition/tests/interfaces/test_ir_cameras.py::Test_FPSWithoutTrigger`

## Typical issues

### Pytest issues
* If pytest says a test passed but it hangs, it's most likely that either 1) a subprocess died, or 2) the main thread is hung. In the first case, pass `-s` to see the traceback printed from the subprocess. Worst case, go in and edit the logging level of the test to `DEBUG` for more informaiton. In the second case, sometimes if queues don't get fully emptied, the main thread can silently hang.

### Azures
* If no frames are collected from the Azures, it's most likely because they are still waiting for the first trigger to arrive. (We run them in "subordinate" mode which means they require an external trigger to truly start acquisition, even once you call .start()). Try running the Azure in a stand-alone notebook in master mode — if that works, then check your sync cable connection (solder joins, is it going into the "sync in" port).  
