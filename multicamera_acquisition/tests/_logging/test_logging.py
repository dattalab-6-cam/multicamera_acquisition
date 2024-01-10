import logging
import multiprocessing as mp
import time
from multicamera_acquisition.logging_utils import logger_process


def dummy_task(queue):

    # Create a logger
    logger = logging.getLogger('dummy_task')

    # Add a handler that uses the shared queue
    logger.addHandler(logging.handlers.QueueHandler(queue))

    # log all messages, debug and up
    logger.setLevel(logging.DEBUG)

    # get the current process
    process = mp.current_process()

    # report initial message
    logger.info(f'Child {process.name} starting.')

    # simulate doing work
    for i in range(5):
        # report a message
        logger.debug(f'Child {process.name} step {i}.')
        # block
        time.sleep(0.1)

    # report final message
    logger.info(f'Child {process.name} done.')


def test_logger():
    queue = mp.Queue()

    # create a logger
    logger = logging.getLogger('app')

    # Add a handler that uses the shared queue, so we can log from this main proc as well
    logger.addHandler(logging.handlers.QueueHandler(queue))

    # log all messages, debug and up
    logger.setLevel(logging.DEBUG)

    # start the logger process
    logger_proc = mp.Process(target=logger_process, args=(queue,))
    logger_proc.start()

    # report initial message
    logger.info('Main process started.')

    # configure child processes
    processes = [mp.Process(target=dummy_task, args=(queue,)) for i in range(5)]

    # start child processes
    for process in processes:
        process.start()

    # wait for child processes to finish
    for process in processes:
        process.join()

    # report final message
    logger.info('Main process done.')

    # shutdown the queue correctly
    queue.put(None)
    logger_proc.join()
