import logging
import sys
def set_logging_config(chosen_level=1):

    # Remove handlers already set (if not, new config will not be set)
    root = logging.getLogger()
    if root.handlers:
        for handler in root.handlers:
            root.removeHandler(handler)

    class InfoFilter(logging.Filter):
        def filter(self, rec):
            return rec.levelno in (logging.WARNING, logging.DEBUG, logging.INFO)

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)

    h1 = logging.StreamHandler(sys.stdout)
    h1.setLevel(logging.DEBUG)
    h1.addFilter(InfoFilter())
    formatter = logging.Formatter('%(asctime)s, %(levelname)s: %(message)s')
    h1.setFormatter(formatter)
    h2 = logging.StreamHandler()
    h2.setLevel(logging.WARNING)
    h2.setFormatter(formatter)

    logger.addHandler(h1)
    logger.addHandler(h2)
    logger.propagate = False

    levels = {0: logging.WARNING,
              1: logging.INFO,
              2: logging.DEBUG}

    if chosen_level not in levels:
        print("Error. Invalid verbosity level %s. Must be 0, 1 or 2" % (chosen_level))
        raise ValueError("Invalid logging level set by -v/--verbose. Choose between 0, 1 and 2.")

    use_level = levels[chosen_level]
    print("Setting logging config to %d" % chosen_level)
    logging.basicConfig(
        level=use_level,
        format="%(asctime)s, %(levelname)s: %(message)s",
        handlers=[h1, h2]
    )