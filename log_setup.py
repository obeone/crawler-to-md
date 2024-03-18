# log_config.py
import logging
import coloredlogs
from tqdm import tqdm


class TqdmHandler(logging.StreamHandler):
    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.write(msg, end="")
        except Exception:
            self.handleError(record)


def setup_logging():
    logger = logging.getLogger()  # Obtenir le logger racine
    handler = TqdmHandler()
    formatter = coloredlogs.ColoredFormatter(
        "%(asctime)s %(hostname)s %(name)s[%(process)d] %(levelname)s %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.WARN)
    coloredlogs.install(level="WARN", logger=logger)
