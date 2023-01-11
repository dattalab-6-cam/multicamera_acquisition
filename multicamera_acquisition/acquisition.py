import multiprocessing as mp
from multicamera_acquisition.interfaces import get_camera
from multicamera_acquisition.videowriter import write_frames
import csv

class AcquisitionLoop(mp.Process):
    ''' A process that acquires images from a camera and writes them to a queue.
    '''
    def __init__(self, write_queue, brand='flir', **camera_params):
        super().__init__()

        self.ready = mp.Event()
        self.primed = mp.Event()
        self.stopped = mp.Event()
        self.write_queue = write_queue
        self.camera_params = camera_params
        self.brand = brand

    def stop(self):
        self.stopped.set()

    def prime(self):
        self.ready.clear()
        self.primed.set()

    def run(self):
        cam = get_camera(brand=self.brand, **self.camera_params)

        self.ready.set()
        self.primed.wait()

        cam.start()
        self.ready.set()

        current_frame = 0
        while not self.stopped.is_set():
            try:
                data = cam.get_array(timeout=1000, get_timestamp=True)
                if len(data) != 0:
                    data = data + tuple([current_frame])
                self.write_queue.put(data)
            except Exception as e:
                # if a frame was dropped, log the lost frame and contiue
                if type(e).__name__ == "SpinnakerException":
                    pass
                else:
                    raise e
            current_frame += 1

        self.write_queue.put(tuple())
        if cam is not None:
            cam.close()


class Writer(mp.Process):
    def __init__(
        self,
        queue,
        video_file_name,
        metadata_file_name,
        camera_serial,
        camera_name,
        **ffmpeg_options
    ):
        super().__init__()
        self.pipe = None
        self.queue = queue
        self.video_file_name = video_file_name
        self.ffmpeg_options = ffmpeg_options
        self.metadata_file_name = metadata_file_name
        self.camera_name = camera_name
        self.camera_serial = camera_serial

        with open(self.metadata_file_name, "w") as metadata_f:
            metadata_writer = csv.writer(metadata_f)
            metadata_writer.writerow(["frame_id", "frame_timestamp", "frame_image_uid"])

    def run(self):
        frame_id = 0
        with open(self.metadata_file_name, "a") as metadata_f:
            metadata_writer = csv.writer(metadata_f)
            while True:
                data = self.queue.get()
                if len(data) == 0:
                    break
                else:
                    # get the computer datetime of the frame
                    frame_image_uid = str(round(time.time(), 5)).zfill(5)
                    img, camera_timestamp, current_frame = data
                    # if the frame is corrupted
                    if img is None:
                        continue
                    metadata_writer.writerow(
                        [
                            current_frame,
                            camera_timestamp,
                            frame_image_uid,
                        ]
                    )
                    self.append(img)
            self.close()

    def append(self, data):
        self.pipe = write_frames(
            self.video_file_name, data[None], pipe=self.pipe, **self.ffmpeg_options
        )

    def close(self):
        if self.pipe is not None:
            self.pipe.stdin.close()