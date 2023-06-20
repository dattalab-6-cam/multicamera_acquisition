Microprocessor controlled multi machine vision camera acquisition (Kinect, Basler, Flir) 
==============================

Python library for parallel video acquisition. It abstracts Basler (pypylon) and flir (pyspin) libraries to allow simultaneous recording from both.

Acquisition is done in parallel using a microcontroller (we use a teensy or arduino) which triggers frame capture. Threads exist for each camera capturing these frames and writing to a video.

In addition, we record input GPIOs on the arduino to sync external data sources to the video frames. 

Authors
- Tim Sainburg
- Caleb Weinreb
- Jonah Pearl

Sources:
    - [simple_pyspin](https://github.com/klecknerlab/simple_pyspin/) is the basis for the camera object. 
    - [Jarvis Motion Capture](https://github.com/JARVIS-MoCap) is mocap software for flir cameras. We used their synchronization as motivation for this library. 

### Installation

### NVIDIA Driver
1. Run software updater on a fresh installation of Ubuntu
2. Check additional drivers to see if NVIDIA drivers are available and reboot your computer
3. Click `Using X.OrgX ...` and run `Apply Changes` and reboot again

### k4aviewer

```
sudo apt-add-repository -y -n 'deb http://archive.ubuntu.com/ubuntu focal main'
sudo apt-add-repository -y 'deb http://archive.ubuntu.com/ubuntu focal universe'
sudo apt-get install -y libsoundio1
sudo apt-add-repository -r -y -n 'deb http://archive.ubuntu.com/ubuntu focal universe'
sudo apt-add-repository -r -y 'deb http://archive.ubuntu.com/ubuntu focal main'

curl -sSL https://packages.microsoft.com/ubuntu/18.04/prod/pool/main/libk/libk4a1.3/libk4a1.3_1.3.0_amd64.deb > /tmp/libk4a1.3_1.3.0_amd64.deb
echo 'libk4a1.3 libk4a1.3/accepted-eula-hash string 0f5d5c5de396e4fee4c0753a21fee0c1ed726cf0316204edda484f08cb266d76' | sudo debconf-set-selections
sudo dpkg -i /tmp/libk4a1.3_1.3.0_amd64.deb

curl -sSL https://packages.microsoft.com/ubuntu/18.04/prod/pool/main/libk/libk4a1.3-dev/libk4a1.3-dev_1.3.0_amd64.deb > /tmp/libk4a1.3-dev_1.3.0_amd64.deb
sudo dpkg -i /tmp/libk4a1.3-dev_1.3.0_amd64.deb

curl -sSL https://packages.microsoft.com/ubuntu/18.04/prod/pool/main/libk/libk4abt1.0/libk4abt1.0_1.0.0_amd64.deb > /tmp/libk4abt1.0_1.0.0_amd64.deb
echo 'libk4abt1.0	libk4abt1.0/accepted-eula-hash	string	03a13b63730639eeb6626d24fd45cf25131ee8e8e0df3f1b63f552269b176e38' | sudo debconf-set-selections
sudo dpkg -i /tmp/libk4abt1.0_1.0.0_amd64.deb

curl -sSL https://packages.microsoft.com/ubuntu/18.04/prod/pool/main/libk/libk4abt1.0-dev/libk4abt1.0-dev_1.0.0_amd64.deb > /tmp/libk4abt1.0-dev_1.0.0_amd64.deb
sudo dpkg -i /tmp/libk4abt1.0-dev_1.0.0_amd64.deb

curl -sSL https://packages.microsoft.com/ubuntu/18.04/prod/pool/main/k/k4a-tools/k4a-tools_1.3.0_amd64.deb > /tmp/k4a-tools_1.3.0_amd64.deb
sudo dpkg -i /tmp/k4a-tools_1.3.0_amd64.deb
```

Then update the udev rules

```
wget https://raw.githubusercontent.com/microsoft/Azure-Kinect-Sensor-SDK/develop/scripts/99-k4a.rules``
sudo mv 99-k4a.rules /etc/udev/rules.d/
```
Plug a Kinect Azure camera into the computer and run `k4aviewer` from the terminal to check the device is discoverable. 

#### Pylon installation
1. Make sure `_apt` has write permission to the proper directories:
```
sudo chown -Rv _apt:root /var/cache/apt/archives/partial/
sudo chmod -Rv 700 /var/cache/apt/archives/partial/
```
2. Go to pylon's [installation webpade](https://www.baslerweb.com/en/downloads/software-downloads/#type=pylonsoftware;version=all;os=linuxx8664bit) and download pylon 7.3.0 Camera Software Suite Linux x86 (64 Bit) - Debian Installer Package
```
cd /to/your/donwload/dir/
tar -xf pylon_7.3.0.27189_linux-x86_64_debs.tar.gz
sudo apt-get install ./pylon_*.deb ./codemeter*.deb
```


##### Setting USB camera settings
For both pylon and spinnaker, you will need to update the settings for UDEV rules (e.g. to raise the maximum USB data transfer size). 
In pylon, this can be done with 
```
sudo sh /opt/pylon/share/pylon/setup-usb.sh
```
In spinnaker, navigate to the spinnaker download folder and run 
```
sudo sh configure_usbfs.sh
```

#### Enabling USB reset

In addition, it is useful to give the library the ability to reset the cameras programatically. 
You can do this by making a .rules file (e.g.`sudo nano /etc/udev/rules.d/99-basler.rules`)

```
SUBSYSTEM=="usb", ATTRS{idVendor}=="xxxx", MODE="0666"
```
For Basler, the ID should be `TTRS{idVendor}=="0x2676"`

Then, reset udev rules.
```
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Then, install the usb library.
```
sudo apt-get install libusb-1.0-0-dev
reboot
```


#### Package installation

You are most likely going to want to customize this code, so just install it with `python setup.py develop` in the main directory. 

```
conda create -n multicam python=3.10
conda activate multicam
git clone https://github.com/timsainb/multicamera_acquisition.git
cd multicamera_acquisition
python setup.py develop
conda install -c anaconda ipykernel
python3 -m ipykernel install --user --name=multicam
pip3 install pypylon, Pillow, matplotlib, numpy, pyusb
pip3 install 
sudo usermod -a -G dialout <your-username>
```


#### NVIDIA GPU encoding patch (Linux)

We use GPU encoding to reduce the CPU load when writing from many cameras simultaneously. For some NVIDIA GPUs encoding more than 3 video streams requires a patch, [located here](https://github.com/keylase/nvidia-patch). Generally this just means running:

```
git clone https://github.com/keylase/nvidia-patch.git
cd nvidia-patch
bash ./patch.sh
```



### Basic usage 
```{python}
from multicamera_acquisition.acquisition import acquire_video

camera_list = [
    {'name': 'top', 'serial': 24535665, 'brand':'basler', 'gain': 12, 'exposure_time': 3000, 'display': False},
    {'name': 'side1', 'serial': 24548223, 'brand':'basler', 'gain': 12, exposure_time': 3000, 'display': False},
    {'name': 'side2', 'serial': 22181547, 'brand':'flir', 'gain': 12, exposure_time': 3000, 'display': False},
    {'name': 'side3', 'serial': 22181612, 'brand':'flir', 'gain': 12, exposure_time': 3000, 'display': False},
]

acquire_video(
    'your/save/location/',
    camera_list,
    framerate = 30,
    recording_duration_s = 10,
    append_datetime=True,
)
```

## Synchronization

Cameras (1) need to be synchronized with other data sources and (2) need to be synchronized with one another (e.g. in the case of dropped frames). We save synchronization files to account for both of these needs. 

### triggerdata.csv

The arduino has a set of GPIOs dedicated to pulse input (by default 4) that can recieve input from an external synchronization. Each row of the triggerdata.csv file corresponds to an input state change in the monitored GPIO channels.

The triggerdata.csv file saves:
- **`pulse_id`**: This is the pulse frame number, according to the microcontroller. This number is computed simply by iterating over the number of frame acquisition pulses that microconstroller has sent out.
- **`arduino_ms`**: This is the microprocessor clock in milliseconds (computed using the `millis()` function. 
- **`flag_{n}`**: This is the state of the GPIO input when a GPIO state change has occured. 

<table border="1" class="dataframe">
  <thead>
    <tr style="text-align:right">
      <th></th>
      <th>pulse_id</th>
      <th>arduino_ms</th>
      <th>flag_0</th>
      <th>flag_1</th>
      <th>flag_2</th>
      <th>flag_3</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <th>0</th>
      <td>1</td>
      <td>110</td>
      <td>0</td>
      <td>0</td>
      <td>1</td>
      <td>1</td>
    </tr>
    <tr>
      <th>1</th>
      <td>90</td>
      <td>1000</td>
      <td>0</td>
      <td>0</td>
      <td>1</td>
      <td>0</td>
    </tr>
    <tr>
      <th>2</th>
      <td>627</td>
      <td>6371</td>
      <td>1</td>
      <td>1</td>
      <td>0</td>
      <td>0</td>
    </tr>
    <tr>
      <th>3</th>
      <td>1165</td>
      <td>11751</td>
      <td>0</td>
      <td>0</td>
      <td>0</td>
      <td>0</td>
    </tr>
  </tbody>
</table>


### {camera}.metadata.csv

The metadata.csv files are created for each individual camera. 

- **`frame_id`**: This is the frame number according to the camera object, corresponding to the number of frames that have been recieved from the camera (including dropped frames). 
- **`frame_timestamp`**: The is the timestamp of the frame, according to the camera. 
- **`frame_image_uid`**: frame_image_uid is the computer time that the frame is being written (within the writer thread). It is computed as `str(round(time.time(), 5)).zfill(5)`
- **`queue_size`**: To allow frames to be written in a separate thread a `multiprocessing.Queue()` is created for each camera. `queue_size` represents the number of frames currently waiting to be written in the queue when the current frame is being written. 



<table border="1" class="dataframe">
  <thead>
    <tr style="text-align:right">
      <th></th>
      <th>frame_id</th>
      <th>frame_timestamp</th>
      <th>frame_image_uid</th>
      <th>queue_size</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <th>0</th>
      <td>0</td>
      <td>287107751173672</td>
      <td>1.682741e+09</td>
      <td>0</td>
    </tr>
    <tr>
      <th>1</th>
      <td>1</td>
      <td>287107760205712</td>
      <td>1.682741e+09</td>
      <td>0</td>
    </tr>
    <tr>
      <th>2</th>
      <td>3</td>
      <td>287108770139128</td>
      <td>1.682741e+09</td>
      <td>0</td>
    </tr>
    <tr>
      <th>3</th>
      <td>4</td>
      <td>287108780126528</td>
      <td>1.682741e+09</td>
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
