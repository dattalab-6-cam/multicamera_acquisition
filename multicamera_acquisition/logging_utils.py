import logging

from multiprocessing import current_process


def setup_child_logger(
    logger_queue,
    level=logging.DEBUG,
    logging_format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
):
    """Given a queue to a parent logger process, set up a logger for the current process.
    The logger's name will be the name of the current process.

    Parameters
    ----------
    queue : multiprocessing.Queue
        A queue to which the logger will write messages.

    level : int
        The logging level to use for the child logger.

    logging_format : str
        The logging format to use for the child logger.

    Returns
    -------
    logger : logging.Logger
        A logger for the current process.

    process_name: str
        The name of the current process.
    """

    # Get the current process name
    process_name = current_process().name

    # Create a logger
    logger = logging.getLogger(process_name)

    # Add a handler that uses the shared queue
    handler = logging.handlers.QueueHandler(logger_queue)
    formatter = logging.Formatter(logging_format)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Set level so we don't burden the queue with things we're not going to log anyways
    logger.setLevel(level)

    return logger
