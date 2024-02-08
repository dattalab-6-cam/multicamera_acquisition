import setuptools
import versioneer

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setuptools.setup(
    name="multicamera_acquisition",
<<<<<<< Updated upstream
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
=======
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
>>>>>>> Stashed changes
)
