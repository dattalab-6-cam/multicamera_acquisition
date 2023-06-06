import multiprocessing as mp

import tkinter as tk
import PIL
from PIL import Image, ImageTk
import cv2
import numpy as np
import logging


class MultiDisplay(mp.Process):
    def __init__(
        self,
        queues,
        camera_names,
        display_downsample=4,
        cameras_per_row=3,
        display_size=(300, 300),
    ):
        super().__init__()
        self.pipe = None
        self.queues = queues
        self.camera_names = camera_names
        self.num_cameras = len(camera_names)
        self.downsample = display_downsample
        self.cameras_per_row = cameras_per_row
        self.display_size = display_size

    def run(self):
        """Displays an image to a window."""

        root = tk.Tk()
        xdim = self.display_size[0] * self.cameras_per_row
        ydim = self.display_size[1] * int(
            np.ceil(self.num_cameras / self.cameras_per_row)
        )
        root.title("Camera view")  # this is the title of the window
        root.geometry(f"{xdim}x{ydim}")  # this is the size of the window

        rowi = 0
        labels = []
        # create a label to hold the image
        for ci, camera_name in enumerate(self.camera_names):
            # create the camera name label
            label_text = tk.Label(root, text=camera_name)
            label_text.grid(row=rowi, column=ci % self.cameras_per_row, sticky="nsew")

            # create the camerea image label
            label = tk.Label(root)  # this is where the image will go
            label.grid(row=rowi + 1, column=ci % self.cameras_per_row, sticky="nsew")

            if (ci + 1) % self.cameras_per_row == 0:
                rowi += 2

            labels.append(label)

        for i in range(self.cameras_per_row):
            root.grid_columnconfigure(i, weight=1)
        for i in range(rowi):
            root.grid_rowconfigure(i, weight=1)

        while True:
            quit = False
            # initialized checks to see if recording has started
            initialized = np.zeros(len(self.queues)).astype(bool)
            for qi, queue in enumerate(self.queues):
                try:
                    data = queue.get(timeout=0.1)
                except Exception as error:
                    if initialized[qi]:
                        logging.info(
                            "{}: Timeout occurred {}".format(
                                self.camera_names[qi], str(error)
                            )
                        )
                    continue
                if len(data) == 0:
                    quit = True
                    break

                # retrieve frame
                if data[0] is not None:
                    initialized[qi] = True
                    frame = data[0][:: self.downsample, :: self.downsample] 
                    frame = cv2.resize(frame, self.display_size)

                    # convert frame to PhotoImage
                    img = ImageTk.PhotoImage(image=PIL.Image.fromarray(frame))

                    # update label with new image
                    labels[qi].config(image=img)
                    labels[qi].image = img
                else:
                    continue
                    #print(f"No data: {self.camera_names[qi]}")

            if quit:
                break
            # update tkinter window
            root.update()
        root.destroy()


class Display(mp.Process):
    def __init__(self, queue, camera_name, display_downsample=4):
        super().__init__()
        self.pipe = None
        self.queue = queue
        self.camera_name = camera_name
        self.display_fcn = lambda x: x
        self.downsample = display_downsample

    def run(self):
        """Displays an image to a window."""

        root = tk.Tk()  # this is the window
        root.title(self.camera_name)  # this is the title of the window
        root.geometry("640x480")  # this is the size of the window

        # create a label to hold the image
        label = tk.Label(root)  # this is where the image will go
        label.pack(fill=tk.BOTH, expand=True)  #

        while True:
            data = self.queue.get()
            if len(data) == 0:
                break

            # retrieve frame
            frame = data[0][:: self.downsample, :: self.downsample]
            frame = cv2.resize(frame, (640, 480))

            # convert frame to PhotoImage
            img = ImageTk.PhotoImage(image=PIL.Image.fromarray(frame))

            # update label with new image
            label.config(image=img)
            label.image = img

            # update tkinter window
            root.update()
