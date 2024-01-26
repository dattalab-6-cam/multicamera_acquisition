from setuptools import find_packages, setup

setup(
    name="multicamera_acquisition",
    packages=find_packages(),
    version="0.1.0",
    description="Python packaamera acquisition with Flir and Basler cameras.",
    author="dattalab",
    license="MIT",
    install_requires=[
        "av"
        "matplotlib"
        "notebook"
        "numpy"
        "opencv-python"
        "pandas"
        "pathlib2"
        "Pillow"
        "pyserial"
        "pyusb"
        "pyyaml"
        "pypylon"
        "tqdm"
    ],
)
