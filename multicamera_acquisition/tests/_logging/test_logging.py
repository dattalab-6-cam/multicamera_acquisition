import logging
from logging import StreamHandler
from logging.handlers import QueueListener
import multiprocessing as mp
import time
from multicamera_acquisition.logging_utils import setup_child_logger


def dummy_task(logger_queue, level=logging.DEBUG):

    # set up a logger for this process
    logger = setup_child_logger(logger_queue, level=level)

    # simulate doing work
    for i in range(5):
        # report a message
        logger.debug(f'step {i}.')
        # block
        time.sleep(0.1)

    # report final message
    logger.info('done.')


def test_logger():

    # Set up a logger for this process
    main_logger = logging.getLogger('main')
    main_logger.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler = StreamHandler()
    handler.setFormatter(formatter)
    main_logger.addHandler(handler)  # Console logging

    # Set up the queue and a listener to receive log messages from child processes
    logger_queue = mp.Queue()
    queue_listener = QueueListener(logger_queue, StreamHandler())
    queue_listener.start()

    # Configure child processes
    main_logger.info('Starting child processes.')
    processes = [mp.Process(target=dummy_task, args=(logger_queue,)) for i in range(5)]

    # Start child processes
    for process in processes:
        process.start()

    # Wait for child processes to finish
    for process in processes:
        process.join()

    # Shutdown the queue correctly
    time.sleep(1)
    queue_listener.stop()


if __name__ == "__main__":
    test_logger()
