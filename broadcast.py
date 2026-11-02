import logging

log = logging.getLogger(__name__)


def register(bot, cfg):
    """Dummy broadcast module: crash rokne ke liye.
    /broadcast aur /fbroadcast abhi kuch nahi karenge."""
    log.info("broadcast module placeholder loaded")
