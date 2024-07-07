import pytest

import ffmpegio.caps as caps
from pprint import pprint

from os import path
import re


@pytest.mark.parametrize("exec", ("ffmpeg", "ffprobe"))
@pytest.mark.parametrize("ver", ("5.1.2", "6.1.1", "7.0.1"))
def test_parser(exec, ver):

    with open(path.join("tests", "assets", f"{exec}_v{ver}.txt"), "rt") as f:

        dump = f.read()

        blocks = {
            m[1]: m[2]
            for b in re.split(r"\n\n+", dump) # group by empty line
            if (m := re.match(r"(.+)?\n(.+)", b, re.MULTILINE | re.DOTALL)) is not None
        }

    dump.split("\n\n")

    dict(b.split("\n", 1) for b in blocks)
    print(dump)


def test_all():
    filters = caps.filters()
    # print(filters)
    caps.codecs()
    encs = caps.encoders()
    decs = caps.decoders()
    caps.formats()
    caps.devices()
    muxes = caps.muxers()
    demuxes = caps.demuxers()
    caps.protocols()
    caps.pix_fmts()
    caps.sample_fmts()
    caps.layouts()
    caps.colors()
    for demux in demuxes.keys():
        caps.demuxer_info(demux)
        break

    for mux in muxes.keys():
        caps.muxer_info(mux)
        break

    for enc in encs.keys():
        caps.encoder_info(enc)
        break

    for dec in decs.keys():
        caps.decoder_info(dec)
        break

    for filter in filters.keys():
        caps.filter_info(filter)
        break

    bsfs = caps.bsfilters()

    for bsf in bsfs:
        caps.bsfilter_info(bsf)
        break


def test_options():
    pprint(caps.options(name_only=True))
    pprint(caps.options("global"))
    pprint(caps.options("video", True))
    pprint(caps.options("per-file"))


if __name__ == "__main__":
    caps.encoder_info("mpeg1video")
