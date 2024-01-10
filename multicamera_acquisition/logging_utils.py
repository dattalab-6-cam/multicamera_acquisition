from multiprocessing import current_process
from multiprocessing import Process
from multiprocessing import Queue
from logging.handlers import QueueHandler
import logging


def logger_process(queue, level=logging.DEBUG):
    """ A process that consumes log messages from a queue, implemented in order to 
    allow logging from many child processes at once.

    Taken from: https://superfastpython.com/multiprocessing-logging-in-python/. 
    See also: https://docs.python.org/3/library/logging.handlers.html and 
    https://docs.python.org/3/howto/logging-cookbook.html#logging-to-a-single-file-from-multiple-processes

    Parameters
    ----------
    queue : multiprocessing.Queue
        A queue to which the logger will write messages.
    """

    # Create a logger
    logger = logging.getLogger('central_logger')

    # Configure a stream handler
    logger.addHandler(logging.StreamHandler())

    # Log all messages, debug and up
    logger.setLevel(level)

    # Run until we get a stop signal
    while True:

        # Consume a log message, block until one arrives
        message = queue.get()

        # Check for shutdown
        if message is None:
            break

        # Log the message
        logger.handle(message)
