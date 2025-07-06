# log_config.py
import logging
from logging import Logger

import coloredlogs
from tqdm import tqdm

logger = Logger("tmp")

class TqdmHandler(logging.StreamHandler):
    """
    Custom logging handler utilizing tqdm for progress bar support in logging.
    This handler allows log messages to be displayed over tqdm progress bars without
    interrupting them.
    """
    def emit(self, record):
        """
        Emit a log record.

        Logs are emitted using tqdm.write to ensure compatibility with tqdm progress
        bars, preventing them from being disrupted by log messages.

        Args:
            record (logging.LogRecord): The log record to be emitted.
        """
        try:
            # Format the log message
            msg = self.format(record)
            # Write the message using tqdm to avoid interfering with progress bars
            tqdm.write(msg, end="")
        except Exception:
            # Handle any errors that occur during logging
            self.handleError(record)

def setup_logging(log_level: str = "WARN"):
    """
    Sets up logging with a custom handler and formatter.

    This function configures the root logger to use a TqdmHandler for output, allowing
    log messages to be displayed over tqdm progress bars. It also uses coloredlogs for
    colored log output.

    Args:
        log_level (str, optional): The minimum log level for messages to be handled.
        Defaults to "WARN".
    """
    global logger

    # Get the root logger
    logger = logging.getLogger()
    # Create an instance of the custom TqdmHandler
    handler = TqdmHandler()
    # Define a formatter with a specific format string, including colored output
    # Updated to show the filename and line number instead of hostname
    formatter = coloredlogs.ColoredFormatter(
        (
            "%(asctime)s %(filename)s:%(lineno)d %(name)s[%(process)d] "
            "%(levelname)s %(message)s"
        )
    )
    # Set the formatter for the handler
    handler.setFormatter(formatter)
    # Add the custom handler to the logger
    logger.addHandler(handler)
    # Set the logger's level to the specified log level
    logger.setLevel(log_level)
    # Install coloredlogs with the specified log level and logger
    coloredlogs.install(level=log_level, logger=logger)

def get_logger():
    """
    Returns the global logger instance.

    Returns:
        logging.Logger: The global logger instance.
    """
    if logger is None:
        setup_logging()

    return logger
