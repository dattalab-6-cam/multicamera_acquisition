Microprocessor-controlled multi-camera video acquisition (Basler, Azure Kinect) 
==============================

Python library for simultaneous video acquisition with Basler cameras (pypylon) and Azure Kinect cameras (pyk4a), with Baslers up to 150 Hz. 

The custom library is necessary in order to interleave the Basler's frames betwee the Azure's sub-frame pulses. Acquisition is done in parallel using a microcontroller to trigger the cameras and IR lights. We use a [Teensy](https://www.pjrc.com/store/teensy41.html), with a [custom PCB](https://github.com/HMS-RIC/Datta-Open-Field-Arena) to control the lights and send triggers to the cameras, but in theory any microcontroller that can go fast enough will work. 

Separate processes exist to capture frames and write the frames to a video for each camera. In addition, we record incoming GPIOs to the microcontroller, to sync external data sources to the video frames.


Authors
- Tim Sainburg
- Caleb Weinreb
- Jonah Pearl
- Jack Lovell
- Sherry Lin
- Kai Fox

Sources:
- [pypylon](https://github.com/basler/pypylon) is used for Basler cameras.
- [pyk4a](https://github.com/etiennedub/pyk4a) is used for Azure Kinect cameras.
- NVIDIA's Video Processing Framework ([VPF](https://github.com/NVIDIA/VideoProcessingFramework/tree/master)) is used to achieve the fastest video writing speeds possible.
- ffmpeg is used as a backup video writer.
- [simple_pyspin](https://github.com/klecknerlab/simple_pyspin/) inspired the camera object though is no longer used.
- [Jarvis Motion Capture](https://github.com/JARVIS-MoCap) is mocap software for flir cameras. We used their synchronization as motivation for this library. 

## Installation

The acquisition code runs anywhere you can install the required packages. As of now, that means Linux and Windows (pyk4a is broken on Macs for the moment, and the NVIDIA VPF can't be installed on Mac either).

Briefly, you will need to install the following to run this code:
- A high-end consumer GPU (e.g. GeForce 4080) with CUDA Toolkit
- Standard software like Git, Anaconda / miniconda, ffmpeg, Arduino, and, optionally, NVIDIA's Video Processing Framework to get the highest possible framerates.
- A few specific sets of software like Pylon, the Azure Kinect SDK, their Python API's, 
- This repo!

Head on over to the [installation instructions](./docs/INSTALL.md) for a detailed explanation of how to get this code up and running.

## Basic usage 
See notebooks folder for examples.


## Synchronization

Cameras (1) need to be synchronized with other data sources and (2) need to be synchronized with one another (e.g. in the case of dropped frames). We save synchronization files to account for both of these needs. 

### triggerdata.csv

The microcontroller has a set of GPIOs dedicated to pulse input that can recieve input from an external synchronization device. Detected changes in the state of these input pins are logged in to a triggerdata.csv file that saves:

- **`time`**: Time that the pin state changed in microseconds from the beginning of acquition (in the microcontroller's clock).
- **`pin`**: The pin that changed state.
- **`state`**: The state that the pin changed to.


### {camera}.metadata.csv

The metadata.csv files are created for each individual camera. 

- **`frame_id`**: This is the frame number according to the camera object, corresponding to the number of frames that have been recieved from the camera (including dropped frames). 
- **`frame_timestamp`**: The is the timestamp of the frame, according to the camera. 
- **`frame_image_uid`**: frame_image_uid is the computer time that the frame is being written (within the writer thread). It is computed as `str(round(time.time(), 5)).zfill(5)`
- **`queue_size`**: To allow frames to be written in a separate thread a `multiprocessing.Queue()` is created for each camera. `queue_size` represents the number of frames currently waiting to be written in the queue when the current frame is being written. 
- **`line_status`**: For synchronization, we read the AUX line. Currently only supported for Basler cameras, but can be added for other cameras. 



<table border="1" class="dataframe">
  <thead>
    <tr style="text-align:right">
      <th></th>
      <th>frame_id</th>
      <th>frame_timestamp</th>
      <th>frame_image_uid</th>
      <th>queue_size</th>
      <th>line_status</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <th>0</th>
      <td>0</td>
      <td>287107751173672</td>
      <td>1.682741e+09</td>
      <td>0</td>
      <td>1</td>
    </tr>
    <tr>
      <th>1</th>
      <td>1</td>
      <td>287107760205712</td>
      <td>1.682741e+09</td>
      <td>0</td>
      <td>1</td>
    </tr>
    <tr>
      <th>2</th>
      <td>3</td>
      <td>287108770139128</td>
      <td>1.682741e+09</td>
      <td>0</td>
      <td>0</td>
    </tr>
    <tr>
      <th>3</th>
      <td>4</td>
      <td>287108780126528</td>
      <td>1.682741e+09</td>
      <td>0</td>
      <td>0</td>
    </tr>
  </tbody>
</table>

### Aligning frames
The parameter `max_video_frames` determines how many video frames are written to a video before creating a new video. For each recording, video clips will be `max_video_frames` frames long, but may drift from one another when frames are lost in each video. 
To align frames, we use the metadata files for each camera. 

### Video duration
The parameter `max_video_frames` determines how many video frames are written to a video before creating a new video. 
For each recording, video clips will be `max_video_frames` frames long, but may drift from one another when frames are lost in each video, thus video frames need to be re-aligned in post processing. 

### Video naming scheme.
Videos are named as `{camera_name}.{camera_serial_number}.{frame_number}.avi`, for example `Top.22181547.30001.avi`.
Here, `frame_number` corresponds to the the `frame_id` value in the `{camera_name}.{camera_serial_number}.metadata.csv` file. 

## TODO
- in the visualization, if skip to the latest frame in the buffer. 



--------

<p><small>Project based on the <a target="_blank" href="https://drivendata.github.io/cookiecutter-data-science/">cookiecutter data science project template</a>. #cookiecutterdatascience</small></p>
