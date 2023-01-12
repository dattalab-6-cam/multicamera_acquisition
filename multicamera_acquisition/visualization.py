import cv2
import multiprocessing as mp
import numpy as np


def display_images(display_queue, display_fcn):

    if display_fcn is None:
        display_fcn = lambda x: x

    try:
        while True:
            data = display_queue.get()
            if len(data) == 0:
                cv2.destroyAllWindows()
                break
            else:
                frame = data[0]
                frame = display_fcn(frame)
                cv2.imshow("ir", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
    except KeyboardInterrupt:
        cv2.destroyAllWindows()


def disp_img(frame, window_name):
    cv2.imshow(window_name, frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        cv2.destroyAllWindows()


class Display(mp.Process):
    def __init__(self, queue, camera_name):
        super().__init__()
        self.pipe = None
        self.queue = queue
        self.camera_name = camera_name
        self.display_fcn = lambda x: x
        # cv2.imshow(self.camera_name, (np.random.rand(10, 10, 3)))

    def run(self):
        """Displays an image to a window."""
        while True:
            data = self.queue.get()
            if len(data) == 0:
                cv2.destroyAllWindows()
                break

            frame = data[0]
            frame = frame[::4, ::4]
            frame = self.display_fcn(frame)
            self.append(frame)
            # cv2.imshow(self.camera_name, frame)
            # if cv2.waitKey(1) & 0xFF == ord("q"):
            #    break
        self.close()

    def append(self, frame):
        self.pipe = disp_img(frame, self.camera_name)

    def close(self):
        cv2.destroyAllWindows()
        if self.pipe is not None:
            self.pipe.stdin.close()
