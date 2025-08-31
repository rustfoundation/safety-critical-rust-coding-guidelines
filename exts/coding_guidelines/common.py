import logging

from tqdm import tqdm

# This is a wrapper around tqdm that allows us to disable it with this global variable
disable_tqdm = False


def get_tqdm(**kwargs):
    kwargs["disable"] = disable_tqdm
    return tqdm(**kwargs)


# Get the Sphinx logger
logger = logging.getLogger("sphinx")
logger.setLevel(logging.WARNING)

# This is what controls the progress bar format
bar_format = "{l_bar}{bar}| {n_fmt}/{total_fmt} {postfix}"
