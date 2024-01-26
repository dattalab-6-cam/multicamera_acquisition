## Installation

The acquisition code runs anywhere you can install the required packages. As of now, that means Linux and Windows (pyk4a is broken on Macs for the moment, and the NVIDIA VPF can't be installed on Mac either).

> [!NOTE]
> The following install instructions assume you are starting on a new computer with no GPU / conda / etc. If you have any of these components installed, you can safely skip their install steps.

***
### NVIDIA Driver

#### Linux
1. Run software updater on a fresh installation of Ubuntu 22.04.
2. Check additional drivers to see if NVIDIA drivers are available and reboot your computer
3. Click `Using X.OrgX ...` and run `Apply Changes` and reboot again

#### Windows
Right-click the NVIDIA logo in the bottom right task-bar thingy, and open the settings page. Look for an option to update the driver. If there isn't one, you may have to update manually by [downloading](https://www.nvidia.com/download/index.aspx) the newest driver available for your device / OS.

***

### Update and install support packages

#### Linux
```
sudo apt install git
sudo apt install curl
sudo apt install build-essential
sudo apt-get update
sudo apt install ffmpeg

sudo apt-get update
sudo apt-get install -y libsoundio1
```

#### Windows
- Install [Git for Windows](https://gitforwindows.org/)
- Download the latest build of ffmpeg with shared libraries. For example, `ffmpeg-release-full-shared.7z` from [here](https://www.gyan.dev/ffmpeg/builds/). Unzip it, rename the resulting folder to something reasonable like `ffmpeg`, move it to a reasonable location, and add the path to the `bin` folder within ffmpeg to your Windows Path (e.g. `C:\path\to\ffmpeg\bin`) ([instructions](https://learn.microsoft.com/en-us/previous-versions/office/developer/sharepoint-2010/ee537574(v=office.14))).

***

### Install Anaconda

#### Linux
```
curl -L https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh -o "$HOME/miniconda3_latest.sh"
chmod +x $HOME/miniconda3_latest.sh
$HOME/miniconda3_latest.sh
```
Restart your terminal for the changes to take effect.

#### Windows
Go to [Anaconda](https://www.anaconda.com/) and install it, following the suggested defaults.

> [!TIP]
> We suggest using [libmamba](https://www.anaconda.com/blog/a-faster-conda-for-a-growing-community) for your base solver to speed things up.

***

### k4aviewer

#### Linux
```
sudo apt-add-repository -y -n 'deb http://archive.ubuntu.com/ubuntu focal main'
sudo apt-add-repository -y 'deb http://archive.ubuntu.com/ubuntu focal universe'

curl -sSL https://packages.microsoft.com/ubuntu/18.04/prod/pool/main/libk/libk4a1.3/libk4a1.3_1.3.0_amd64.deb > /tmp/libk4a1.3_1.3.0_amd64.deb
echo 'libk4a1.3 libk4a1.3/accepted-eula-hash string 0f5d5c5de396e4fee4c0753a21fee0c1ed726cf0316204edda484f08cb266d76' | sudo debconf-set-selections
sudo dpkg -i /tmp/libk4a1.3_1.3.0_amd64.deb

curl -sSL https://packages.microsoft.com/ubuntu/18.04/prod/pool/main/libk/libk4a1.3-dev/libk4a1.3-dev_1.3.0_amd64.deb > /tmp/libk4a1.3-dev_1.3.0_amd64.deb
sudo dpkg -i /tmp/libk4a1.3-dev_1.3.0_amd64.deb

curl -sSL https://packages.microsoft.com/ubuntu/18.04/prod/pool/main/libk/libk4abt1.0/libk4abt1.0_1.0.0_amd64.deb > /tmp/libk4abt1.0_1.0.0_amd64.deb
echo 'libk4abt1.0 libk4abt1.0/accepted-eula-hash string	03a13b63730639eeb6626d24fd45cf25131ee8e8e0df3f1b63f552269b176e38' | sudo debconf-set-selections
sudo dpkg -i /tmp/libk4abt1.0_1.0.0_amd64.deb

curl -sSL https://packages.microsoft.com/ubuntu/18.04/prod/pool/main/libk/libk4abt1.0-dev/libk4abt1.0-dev_1.0.0_amd64.deb > /tmp/libk4abt1.0-dev_1.0.0_amd64.deb
sudo dpkg -i /tmp/libk4abt1.0-dev_1.0.0_amd64.deb

curl -sSL https://packages.microsoft.com/ubuntu/18.04/prod/pool/main/k/k4a-tools/k4a-tools_1.3.0_amd64.deb > /tmp/k4a-tools_1.3.0_amd64.deb
sudo dpkg -i /tmp/k4a-tools_1.3.0_amd64.deb
```

Then update the udev rules

```
wget https://raw.githubusercontent.com/microsoft/Azure-Kinect-Sensor-SDK/develop/scripts/99-k4a.rules
sudo mv 99-k4a.rules /etc/udev/rules.d/
```

If you are using Ubuntu 22.04, you will need to run the following lines to ensure the drivers and packages are in the correct location. 
```
find / -name libstdc++.so.6 2>/dev/null
export LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libstdc++.so.6
```

#### Windows
Install the latest version of the Azure Kinect SDK from their GitHub page: https://github.com/microsoft/Azure-Kinect-Sensor-SDK/blob/develop/docs/usage.md

> [!IMPORTANT]
> Plug a Kinect Azure camera into the computer and run `k4aviewer` from the terminal to check the device is discoverable. If not, debug it.

***

### Pylon installation

#### Linux
1. Go to pylon's [installation webpage](https://www.baslerweb.com/en/downloads/software-downloads/#type=pylonsoftware;version=all;os=linuxx8664bit) and download `pylon 7.3.0 Camera Software Suite Linux x86 (64 Bit) - Debian Installer Package`

```
cd /to/your/donwload/dir/
tar -xf pylon_7.3.0.27189_linux-x86_64_debs.tar.gz
sudo apt-get install ./pylon_*.deb
sudo apt-get install ./codemeter*.deb
```
Pylon should now be on your applications grid. If it does not launch upon clicking it, then try the following:
```
sudo apt-get install libxcb-xinput0
```
If that does not work, then run the below and use the error message to debug what possibly went wrong
```
export QT_DEBUG_PLUGINS=1
/opt/pylon/bin/pylonviewer
```

#### Windows
Install pylon 7.3.0 from their [webpage](https://www2.baslerweb.com/en/downloads/software-downloads/#type=pylonsoftware;version=all;os=windows).

***

### Setting USB camera settings
#### Linux
For Pypylon to record videos and transfer large amount of data (i.e. video data) over USB, you will need to update the settings for UDEV rules (e.g. to raise the maximum USB data transfer size). 
In pylon, this can be done with 
```
sudo sh /opt/pylon/share/pylon/setup-usb.sh
```

#### Windows
> [!WARNING]
> This is TBD for Windows

***

### Enabling USB reset
Give the library the ability to reset the cameras programatically.
You can do this by making a .rules file using `nano` or `vim`:
```
cd /etc/udev/rules.d/
sudo nano 99-basler.rules
```

Then, add the following line to the file:
```
SUBSYSTEM=="usb", ATTRS{idVendor}=="0x2676", MODE="0666"
```
Save (CTRL + O) and exit (CTRL + X) `nano`.

Then, reset udev rules.
```
sudo udevadm control --reload-rules && sudo udevadm trigger
```

Then, install the usb library.
```
sudo apt-get install libusb-1.0-0-dev
reboot
```

#### Windows
> [!WARNING]
> This is TBD for Windows, although the python library that we use claims to support Windows.

***

### Arduino IDE

#### Linux
1. Download the Arduino IDE AppImage from Arduino's [website](https://www.arduino.cc/en/software)
2. (Optional) Move to a better location:
```
mv ~/Downloads/arudino-*.Appimage /path/to/where/you/want/arduino-ide
```
3. Open the folder viewer where you arudino app image lives
4. Right-click the file,
5. Choose Properties,
6. Select Permissions tab,
7. Tick the Allow executing file as program box. 

If double clicking the app image does not open the IDE try the following:
```
sudo add-apt-repository universe
sudo apt install libfuse2
```
If you want to have the IDE available in your Desktop menu then fllow the instructions at this [link](https://askubuntu.com/questions/1311600/add-an-appimage-application-to-the-top-menu-bar)

#### Windows
1. Download the Arduino IDE for Windows from Arduino's [website](https://www.arduino.cc/en/software) and install it.

### Installing the `multicamera_acquisition` python package
(This is envrionment agnostic.)

```
conda create -n multicam python=3.10
conda activate multicam
git clone https://github.com/dattalab-6-cam/multicamera_acquisition.git
cd multicamera_acquisition
pip install -e .
```

### Add user to dialout group to access serial ports (Linux only)
```
sudo usermod -a -G dialout <your-username>
```
***
### NVIDIA GPU encoding patch

#### Linux
We use GPU encoding to reduce the CPU load when writing from many cameras simultaneously. For some NVIDIA GPUs encoding more than 3 video streams requires a patch, [located here](https://github.com/keylase/nvidia-patch). Generally this just means running:

```
git clone https://github.com/keylase/nvidia-patch.git
cd nvidia-patch
bash ./patch.sh
```

#### Windows
The same patch is required, but it is a bit more involved to install: https://github.com/keylase/nvidia-patch/tree/master/win. That said, we have had success using it.

***
<!-- TODO: Test this part, NVIDIA VPF not tested on laptop-->
### NVIDIA VideoProcessingFramework
We use the NVIDIA VideoProcessingFramework to encode videos using the GPU. You can find more information in the official documentation [here](https://github.com/NVIDIA/VideoProcessingFramework).

#### Linux
Follow [this guide](https://docs.nvidia.com/video-technologies/video-codec-sdk/12.0/ffmpeg-with-nvidia-gpu/index.html#compiling-for-linux) to build FFmpeg with Nvidia GPU from source.

```
# Install dependencies
apt install -y \
          libavfilter-dev \
          libavformat-dev \
          libavcodec-dev \
          libswresample-dev \
          libavutil-dev\
          wget \
          build-essential \
          git

# Install CUDA Toolkit (if not already present)
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.0-1_all.deb
sudo dpkg -i cuda-keyring_1.0-1_all.deb
sudo apt-get update
sudo apt-get install -y cuda
# Ensure nvcc to your $PATH (most commonly already done by the CUDA installation)
export PATH=/usr/local/cuda/bin:$PATH

# Install VPF
pip3 install git+https://github.com/NVIDIA/VideoProcessingFramework
# or if you cloned this repository
pip3 install .
```

#### Windows
Follow the guide in the official documentation [here](https://github.com/NVIDIA/VideoProcessingFramework). We have tested install with Visual Studio 2019, and [installing CUDA Toolkit via Conda](https://docs.nvidia.com/cuda/cuda-quick-start-guide/index.html#conda). This is much easier than trying to install the binaries yourself or (god forbid) compile it.
>[!IMPORTANT]
>The final step of the VPF install process is to "Install from the root directory of this repository indicating the location of the compiled FFMPEG in a Powershell console." After cloning the repo to a reasonable location, you will need to initiate conda in Windows Powershell before you can actually do the install correctly — otherwise you will be installing into your base environment instead of into your conda environment that we created a few steps ago. The steps to do this are as follows:
> 1. Open an "Anaconda Powershell"
> 2. Run `conda init powershell`
> 3. Open a (plain) Powershell instance as an administrator
> 4. Run the command `Set-ExecutionPolicy Bypass -Scope CurrentUser` to allow the conda script to run in Powershell
> 5. Re-open a (plain) Powershell window and you should see conda initiated as signaled by the `(base)` on the left of the command entry line.
> 6. Run `conda activate multicam`
> 7. Now you can run the commands that VPF suggests:
> ```
> # Indicate path to your FFMPEG installation (with subfolders `bin` with DLLs, `include`, `lib`)
> $env:SKBUILD_CONFIGURE_OPTIONS="-DTC_FFMPEG_ROOT=C:/path/to/your/ffmpeg/installation/ffmpeg/"
> ```
> Note that this will **only** work with forward slashes as shown (despite the fact that Windows uses backslashes).
> ```
> cd [to the cloned the VPF repo]
> pip install .
> python
> >>> import PyNvCodec
> ```

***
