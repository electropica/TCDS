#!/usr/bin/env python3
import configparser

import sys
import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

Gst.init(None)
config = configparser.ConfigParser()
config.read("/opt/tcds/config/tcds-player.conf")
MEDIA_FILE = config.get("player", "media")

def play(filename):
    pipeline = Gst.parse_launch(
        f'filesrc location="{filename}" ! qtdemux ! '
        'h264parse ! v4l2h264dec ! kmssink'
    )

    pipeline.set_state(Gst.State.PLAYING)

    bus = pipeline.get_bus()

    while True:
        message = bus.timed_pop_filtered(
            Gst.CLOCK_TIME_NONE,
            Gst.MessageType.ERROR | Gst.MessageType.EOS
        )

        if message.type == Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            print(f"Erreur: {error}", file=sys.stderr)
            if debug:
                print(debug, file=sys.stderr)
            break

        if message.type == Gst.MessageType.EOS:
            pipeline.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, 0)

    pipeline.set_state(Gst.State.NULL)


if __name__ == "__main__":
    play(MEDIA_FILE)
