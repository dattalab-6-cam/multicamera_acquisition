from multicamera_acquisition.interfaces.camera_base import BaseCamera, CameraError
import numpy as np

from arena_api.__future__.save import Writer
from arena_api.buffer import BufferFactory
from arena_api.enums import PixelFormat
from arena_api.system import system
import logging
import time 
import ctypes

class LucidCamera(BaseCamera):
    def __init__(self, index=0, lock=True, **kwargs):
        """
        Parameters
        ----------
        index : int or str (default: 0)
            If an int, the index of the camera to acquire.  If a string,
            the serial number of the camera.
        lock : bool (default: True)
            If True, setting new attributes after initialization results in
            an error.
        """
        self.serial_number = index
        
        # gets the devices
        devices = find_helios_devices()

        n_devices = len(devices)
        # debug: print("Found %d camera(s)" % n_devices)
        camera_serials = np.array([c.nodemap['DeviceSerialNumber'].value for c in devices])

        if n_devices == 0:
            raise CameraError("No cameras detected.")
        if isinstance(index, str):
            if not np.any(camera_serials == index):
                raise CameraError("Camera with serial number %s not found." % index)
            index = np.where(camera_serials == index)[0][0]
            self.cam = devices[index]
        else:
            raise CameraError("Index / serial number must be string")

        del devices
        
        self.running = False

    def init(self):
        """Initializes the camera.  Automatically called if the camera is opened
        using a `with` clause."""
        
        logging.log(logging.DEBUG, f"running init for camera {self.serial_number}")
        # Get device stream nodemap
        tl_stream_nodemap = self.cam.tl_stream_nodemap
        # Enable stream auto negotiate packet size
        tl_stream_nodemap['StreamAutoNegotiatePacketSize'].value = True
        # Enable stream packet resend
        tl_stream_nodemap['StreamPacketResendEnable'].value = True
        
        # reset device nodemap
        self.cam.nodemap['UserSetSelector'].value = 'Default'
        self.cam.nodemap['UserSetLoad'].execute()
        
        # Store nodes' initial values
        self.nodemap = self.cam.nodemap
            
        # set distance paramters
        #self.nodemap['Scan3dDistanceUnit'].value = 'Millimeter'
        self.nodemap['Scan3dDistanceMin'].value = 150
        #self.nodemap['Scan3dDistanceMax'].value = 1000
        
        # operating mode
        #   'Distance1250mmSingleFreq', 
        #   'Distance3000mmSingleFreq',
        #   'Distance4000mmSingleFreq', 
        #   'Distance5000mmMultiFreq', 
        #   'Distance6000mmSingleFreq', 
        #   'Distance8300mmMultiFreq', 
        #   'HighSpeedDistance625mmSingleFreq',
        #   'HighSpeedDistance1250mmSingleFreq', 
        #   'HighSpeedDistance2500mmSingleFreq'
        self.nodemap['Scan3dOperatingMode'].value = 'HighSpeedDistance2500mmSingleFreq'#'HighSpeedDistance625mmSingleFreq'
        
        # set pixel format
        pixel_format = PixelFormat.Coord3D_ABCY16
        self.nodemap.get_node('PixelFormat').value = pixel_format
        
        # set exposure time
        self.nodemap['ExposureTimeSelector'].value = 'Exp1000Us'
        # set gain
        self.nodemap['ConversionGain'].value = 'Low'
        # Enable spatial filter
        self.nodemap['Scan3dSpatialFilterEnable'].value = True
        # disable confidence threshold
        self.nodemap['Scan3dConfidenceThresholdEnable'].value = True #False
        
        # get coordinate scale from nodemap
        self.nodemap["Scan3dCoordinateSelector"].value = "CoordinateC"
        self.scale_z = self.nodemap["Scan3dCoordinateScale"].value
        
        # set trigger input
        self.nodemap['TriggerSelector'].value = 'FrameStart'
        self.nodemap['TriggerMode'].value = 'On' # 'On'
        self.nodemap['TriggerSource'].value = 'Line2' # Software, Line2
        
        logging.log(logging.DEBUG, f"almost done running init for camera {self.serial_number}")
        #print('STILL RUNNING INIT')
        
        # wait until trigger is armed
        #trigger_armed = False
        #while trigger_armed is False:
        #    trigger_armed = bool(self.nodemap['TriggerArmed'].value)
        
        logging.log(logging.DEBUG, f"done running init for camera {self.serial_number}")


    def start(self):
        "Start recording images."
        #print('STARTING STREAM')
        #max_recording_hours = 60
        #max_recording_frames = max_recording_hours * 60 * 60 * 200
        self.cam.start_stream(20)
        self.running = True

    def stop(self):
        "Stop recording images."
        self.running = False
        self.cam.stop_stream()

        #print('DESTROYING DEVICE')
        # Destroy device. Optional, implied by closing of module
        system.destroy_device()
        
    def close(self):
        self.stop()
        system.destroy_device()
        del self.cam
        self.camera_attributes = {}
        self.camera_methods = {}
        self.camera_node_types = {}
        self.initialized = False

    def get_image(self, timeout=None):
        """Get an image from the camera.
        Parameters
        ----------
        timeout : int (default: None)
            Wait up to timeout milliseconds for an image if not None.
                Otherwise, wait indefinitely.
        Returns
        -------
        img : PySpin Image
        """
        try:
            if timeout is None:
                timeout = 10000
            # TODO, fix so this isn't a software trigger...
            self.nodemap['TriggerSoftware'].execute()
            #trigger_armed = False
            #while trigger_armed is False:
            #    trigger_armed = bool(self.nodemap['TriggerArmed'].value)
            buffer_3d = self.cam.get_buffer(timeout=timeout)
            depth_image = get_depth_image(buffer_3d, self.scale_z)
            timestamp = buffer_3d.timestamp_ns
            self.cam.requeue_buffer(buffer_3d)
            return depth_image, timestamp
        except TimeoutError:
            return None, None

    def get_array(self, timeout=None, get_timestamp=False):
        """Get an image from the camera.
        Parameters
        ----------
        timeout : int (default: None)
            Wait up to timeout milliseconds for an image if not None.
                Otherwise, wait indefinitely.
        get_timestamp : bool (default: False)
            If True, returns timestamp of frame f(camera timestamp)
        Returns
        -------
        img : Numpy array
        tstamp : int
        """
        #if self.cam.IsGrabbing() == False:
        #    raise ValueError("Camera is not set up to grab frames.")

        img_array, tstamp = self.get_image(timeout)
            
        #if img.GrabSucceeded():
        #    img_array = img.Array.astype(np.uint8)
        #    if get_timestamp:
        #        tstamp = img.GetTimeStamp()
        #    else:
        #        tstamp = None
        #else:
        #    img_array = None
        #    tstamp = None

        if get_timestamp:
            return img_array, tstamp
        else:
            return img_array

    def get_info(self, name=None):
        """Gen information on a camera node (attribute or method).
        Parameters
        ----------
        name : string
            The name of the desired node
        Returns
        -------
        info : dict
            A dictionary of retrieved properties.  *Possible* keys include:
                - `'access'`: read/write access of node.
                - `'description'`: description of node.
                - `'value'`: the current value.
                - `'unit'`: the unit of the value (as a string).
                - `'min'` and `'max'`: the min/max value.
        """
        raise NotImplementedError

    def document(self):
        """Creates a MarkDown documentation string for the camera."""
        raise NotImplementedError


# Corrected function
def ctypes_to_numpy(ptr, shape):
    # Cast the ctypes pointer to a numpy array with the specified shape
    return np.ctypeslib.as_array(ptr, shape)

def find_helios_devices(tries_max = 6, sleep_time_secs = 1):
    '''
    This function waits for the user to connect a device before raising
    an exception
    '''
    devices_found = False
    for tries in range(tries_max):  # Wait for device for 60 seconds
        devices = system.create_device()
        if not devices:
            print(
            f'Try {tries+1} of {tries_max}: waiting for {sleep_time_secs} '
            f'secs for a device to be connected!')
            time.sleep(sleep_time_secs)
            tries += 1
        else:
            # successfully found devices
            devices_found = True
            break
    if not devices_found:
        raise Exception(f'No device found! Please connect a device and run '
                        f'the example again.')
    
    # remove any non Helios devices
    for di, device in enumerate(devices):
        try:
            device.nodemap['Scan3dOperatingMode']
        except:
            # remove device by index
            devices.pop(di)
            
    if len(devices) == 0:
        raise Exception(f'No Helios device found! Please connect a device and run '
                        f'the example again.')
    return devices


def get_depth_image(buffer_3d, scale_z):

    # 3D buffer info -------------------------------------------------

    # "Coord3D_ABCY16s" and "Coord3D_ABCY16" pixelformats have 4
    # channels pre pixel. Each channel is 16 bits and they represent:
    #   - x position
    #   - y postion
    #   - z postion
    #   - intensity
    # the value can be dynamically calculated this way:
    #   int(buffer_3d.bits_per_pixel/16) # 16 is the size of each channel
    Coord3D_ABCY16_channels_per_pixel = buffer_3d_step_size = 4

    # Buffer.pdata is a (uint8, ctypes.c_ubyte) pointer. "Coord3D_ABCY16"
    # pixelformat has 4 channels, and each channel is 16 bits.
    # It is easier to deal with Buffer.pdata if it is casted to 16bits
    # so each channel value is read/accessed easily.
    # "Coord3D_ABCY16" might be suffixed with "s" to indicate that the data
    # should be interpereted as signed.
    pdata_16bit = ctypes.cast(buffer_3d.pdata, ctypes.POINTER(ctypes.c_int16))

    number_of_pixels = buffer_3d.width * buffer_3d.height

    # Calculate the total size of the buffer in 16-bit units
    total_size = number_of_pixels * buffer_3d_step_size

    # Create a NumPy array that views the data as 16-bit signed integers
    buffer_as_array = np.ctypeslib.as_array(pdata_16bit, shape=(total_size,))

    # Extract every fourth value starting from the third value, which is the Z coordinate
    z_values = buffer_as_array[2::buffer_3d_step_size]

    # Convert z values from device units to millimeters (if necessary)
    depth_array_mm = z_values * scale_z

    # Reshape the flat array into the 2D image format (height, width)
    depth_image = depth_array_mm.reshape((buffer_3d.height, buffer_3d.width))

    return depth_image

