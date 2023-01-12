import multiprocessing as mp

import tkinter as tk
import PIL
from PIL import Image, ImageTk
import cv2


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

        root = tk.Tk()
        root.title(self.camera_name)
        root.geometry("640x480")

        # create a label to hold the image
        label = tk.Label(root)
        label.pack(fill=tk.BOTH, expand=True)

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
