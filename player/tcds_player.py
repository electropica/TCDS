#!/usr/bin/env python3

import sys
import json
import os
import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst
from gi.repository import GLib
Gst.init(None)

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


def play_image(filename, duration):
    pipeline = Gst.parse_launch(
        f'filesrc location="{filename}" ! jpegdec ! imagefreeze ! '
        'videoconvert ! videoscale ! kmssink sync=false'
    )
    pipeline.set_state(Gst.State.PLAYING)
    loop = GLib.MainLoop()
    GLib.timeout_add_seconds(max(1, int(duration)), loop.quit)
    loop.run()
    pipeline.set_state(Gst.State.NULL)


def play_playlist(path):
    with open(path, "r", encoding="utf-8") as file:
        playlist = json.load(file)
    for item in playlist:
        if os.path.isfile(item["path"]):
            play_image(item["path"], item.get("duration", 10))


if __name__ == "__main__":
    playlist = "/opt/tcds/config/tcds-playlist.json"
    if os.path.isfile(playlist):
        play_playlist(playlist)
    else:
        play(sys.argv[1] if len(sys.argv) > 1 else "/opt/tcds/media/current.mp4")
