multicamera_acquisition
==============================

Python library for parallel video acquisition. It abstracts Basler (pypylon) and flir (pyspin) libraries to allow simultaneous recording from both.

Acquisition is done in parallel using a microprocessor (we use an arduino) which triggers frame capture. Threads exist for each camera capturing these frames and writing to a video.

In addition, we record input GPIOs on the arduino to sync external data sources to the video frames. 

Authors
- Tim Sainburg
- Caleb Weinreb
- Jonah Pearl

Sources:
    - [simple_pyspin](https://github.com/klecknerlab/simple_pyspin/) is the basis for the camera object. 
    - [Jarvis Motion Capture](https://github.com/JARVIS-MoCap) is mocap software for flir cameras. We used their synchronization as motivation for this library. 

### Installation

Before installation: You should install pylon and pypylon if you are using Basler cameras, and spinnaker and pypin if you are using Flir cameras. 

You are most likely going to want to customize this code, so just install it with `python setup.py develop` in the main directory. 


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


--------

<p><small>Project based on the <a target="_blank" href="https://drivendata.github.io/cookiecutter-data-science/">cookiecutter data science project template</a>. #cookiecutterdatascience</small></p>
