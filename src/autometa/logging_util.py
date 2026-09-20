"""Shared logging setup for the autometa CLI and its worker processes."""

import logging


def setup_logging(verbosity: int) -> logging.Logger:
    """Set up logging for CLI and runner processes.

    :param verbosity: 0=WARNING, 1=INFO, >=2=DEBUG
    :return: The 'autometa:cli' logger
    """
    verbosity_level_map = {0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}
    logging.basicConfig(
        format="%(asctime)s - %(levelname)s - %(message)s",
        level=verbosity_level_map.get(verbosity, logging.DEBUG),
    )
    return logging.getLogger("autometa:cli")
