# TODO add function to guess media type given extension
from __future__ import annotations

import logging

logger = logging.getLogger("ffmpegio")

from typing import Any, Literal, Union, Tuple, Dict

import re, fractions, subprocess as sp
from collections import namedtuple
from fractions import Fraction
from functools import partial, lru_cache

from .path import ffmpeg as _ffmpeg
from .errors import FFmpegError

# fmt:off
__all__ = ["options", "filters", "codecs", "coders", "formats", "devices",
    "muxers", "demuxers", "bsfilters", "protocols", "pix_fmts", "sample_fmts",
    "layouts", "colors", "demuxer_info", "muxer_info", "encoder_info",
    "decoder_info", "filter_info", "bsfilter_info", "frame_rate_presets",
    "video_size_presets"]
# fmt:on

_ffCodecRegexp = re.compile(
    r"([D.])([E.])([VAS])([I.])([L.])([S.])\s+([^=\s][\S]*)\s+(.*)"
)  # g
_ffEncodersRegexp = re.compile(r"\s+\(encoders:([^\)]+)\)")
_ffDecodersRegexp = re.compile(r"\s+\(decoders:([^\)]+)\)")
_coderRegexp = re.compile(
    r"([VAS])([F.])([S.])([X.])([B.])([D.])\s+([^=\s]\S*)\s+(.*)"
)  # g
_formatRegexp = re.compile(r"([D ]) *([E ]) +(\S+) +(.*)")  # g
_filterRegexp = re.compile(
    r"([T.])([S.])([C.])\s+(\S+)\s+(A+|V+|N|\|)->(A+|V+|N|\|)\s+(.*)"
)  # g


@lru_cache()
def _exec(
    gopts: tuple[str],
    sp_kwargs: tuple[tuple[str, Any]] | None = None,
):

    sp_opts = {"stdout": sp.PIPE, "encoding": "utf-8"}

    if sp_kwargs is not None:
        sp_opts = {**dict(sp_kwargs), **sp_opts}

    out = _ffmpeg(["-hide_banner", *gopts], **sp_opts)

    if out.returncode or out.stdout.count("\n") == 1:
        raise FFmpegError(out.stdout)

    return out.stdout


def _run(
    cap: str,
    sp_kwargs: dict[str, Any] | None = None,
):
    return _exec((f"-{cap}",), sp_kwargs and tuple(sp_kwargs.items()))


def _run_help(
    type: str,
    name: str | None = None,
    sp_kwargs: dict[str, Any] | None = None,
):
    return _exec(
        ("-help", type if name is None else f"{type}={name}"),
        sp_kwargs and tuple(sp_kwargs.items()),
    )


def options(
    type: (
        Literal["per-file", "video", "audio", "subtitle", "general", "global"] | None
    ) = None,
    name_only: bool | None = False,
    return_desc: bool | None = False,
    sp_kwargs: dict[str, Any] | None = None,
):
    """get FFmpeg command options

    :param type: specify option type to return, defaults to None
    :type type: "per-file"\|"video"\|"audio"\|"subtitle"\|"general"\|"global"\|None, optional
    :param name_only: True to only return option names, defaults to False
    :type name_only: bool, optional
    :param return_desc: True to also return option description, defaults to False
    :type return_desc: bool, optional
    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: dict of types of options
    :rtype: dict(dict or tuple) if type not specified
    """

    lines = _run_help("long", sp_kwargs=sp_kwargs).split("\n")
    ginds = [
        (i + 1, l[:-1].lower())
        for i, l in enumerate(lines)
        if len(l) and l[0] not in "- \t" and l[-1] == ":"
    ]
    ginds.append((len(lines) + 1, None))

    def parse_line(s):
        m = re.match(r"\s*-(.+?) ([^ ]+?)? {2,}(.*)$", s)
        return (m[1], m[2], m[3]) if m else None

    raw_opts = (
        (
            l,
            {
                o[0]: o[1:]
                for o in (parse_line(s) for s in lines[i0 : i1 - 1])
                if o is not None
            },
        )
        for (i0, l), (i1, _) in zip(ginds[:-1], ginds[1:])
    )

    opts = {
        "video": {},
        "audio": {},
        "subtitle": {},
        "general": {},
        "global": {"overwrite": ("bool", "[ffmpegio] combining -y/-n options")},
    }
    for gname, gopts in raw_opts:
        if "video" in gname:
            opts["video"].update(gopts)
        elif "audio" in gname:
            opts["audio"].update(gopts)
        elif "subtitle" in gname:
            opts["subtitle"].update(gopts)
        elif "per-file" in gname:
            opts["general"].update(gopts)
        else:
            opts["global"].update(gopts)

    if type == "per-file":
        opts = {
            "per-file": {
                k: v for t, o in opts.items() if t != "global" for k, v in o.items()
            }
        }

    return (
        ({t: tuple(o) for t, o in opts.items()} if type is None else tuple(opts[type]))
        if name_only
        else (
            (
                opts
                if return_desc
                else {t: {k: v[0] for k, v in o.items()} for t, o in opts.items()}
            )
            if type is None
            else (
                opts[type] if return_desc else {k: v[0] for k, v in opts[type].items()}
            )
        )
    )


# fmt:off
FilterSummary = namedtuple(
    "FilterSummary",
    ["description", "input", "num_inputs", "output", "num_outputs",
        "timeline_support", "slice_threading", "command_support"],
)
# fmt:on


def filters(
    type: Literal["audio", "video", "dynamic"] | None = None,
    sp_kwargs: dict[str, Any] | None = None,
):
    """get FFmpeg filters

    :param type: specify input or output stream type, defaults to None
    :type type: 'audio'|'video'|'dynamic', optional
    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: dict of summary of the filters
    :rtype: dict(key,FilterSummary)

    Each key of the returned dict is a name of a filter and its value is a
    FilterSummary namedtuple with the following items:

    ================  ========  ===============================================
    Key               type      description
    ================  ========  ===============================================
    description       str       Short description of the filter
    input             str       Input stream type: 'audio'|'video'|'dynamic'
    num_inputs        int|None  Number of inputs or None if 'dynamic'
    output            str       Output stream type: 'audio'|'video'|'dynamic'
    num_outputs       int|None  Number of outputs or None if 'dynamic'
    timeline_support  bool      True if supports timeline editing
    slice_threading   bool      True if supports threading
    command_support   bool      True if supports command input from stdin
    ================  ========  ===============================================
    """

    stdout = _run("filters", sp_kwargs)
    types = {"A": "audio", "V": "video", "N": "dynamic", "|": "none"}

    data = {}
    for match in _filterRegexp.finditer(stdout):
        intype = types[match[5][0]]
        outtype = types[match[6][0]]
        data[match[4]] = FilterSummary(
            description=match[7],
            input=intype,
            num_inputs=(
                0
                if intype == "none"
                else len(match[5]) if intype != "dynamic" else None
            ),
            output=outtype,
            num_outputs=(
                0
                if outtype == "none"
                else len(match[6]) if outtype != "dynamic" else None
            ),
            timeline_support=match[1] == "T",
            slice_threading=match[2] == "S",
            command_support=match[3] == "C",
        )

    if type is not None:
        data = {k: v for k, v in data.items() if v.input == type or v.output == type}

    return data


def codecs(
    type: Literal["decoder", "encoder"] | None = None,
    stream_type: Literal["audio", "video", "subtitle"] | None = None,
    sp_kwargs: dict[str, Any] | None = None,
):
    """get FFmpeg codecs

    :param type: Specify to list only decoder or encoder, defaults to None
    :type type: 'decoder'|'encoder', optional
    :param stream_type: Specify to stream type, defaults to None
    :type stream_type: 'audio'|'video'|'subtitle', optional
    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: summary of FFmpeg codecs
    :rtype: dict

    Each key of the returned dict is a name of a codec and its value is a dict
    with the following items:

    ================  =========  ===============================================
    Key               type       description
    ================  =========  ===============================================
    type              str        Stream type: 'audio'|'video'|'subtitle'
    description       str        Short description of the codec
    can_decode        bool       True if FFmpeg can decode
    decoders          list(str)  List of compatible decoders
    can_encode        bool       True if FFmpeg can encode
    encoders          list(str)  List of compatible encoders
    intra_frame_only  bool       True if codec only uses intra-frame coding
    is_lossy          bool       True if codec can do lossy compression
    is_lossless       bool       True if codec can do lossless compression
    ================  =========  ===============================================
    """
    stdout = _run("codecs", sp_kwargs)
    data = {}
    for match in _ffCodecRegexp.finditer(stdout):
        stype = {"V": "video", "A": "audio", "S": "subtitle"}[match[3]]

        desc = match[8]
        encoders = _ffEncodersRegexp.match(desc)
        if encoders:
            desc = desc.slice(0, encoders.index) + desc.slice(
                encoders.index + encoders[0].length
            )
        encoders = encoders[1].trim().split(" ") if encoders else None

        decoders = _ffDecodersRegexp.match(desc)
        if decoders:
            desc = desc.slice(0, decoders.index) + desc.slice(
                decoders.index + decoders[0].length
            )
        decoders = decoders[1].trim().split(" ") if decoders else None

        data[match[7]] = {
            "type": stype,
            "description": desc,
            "can_decode": match[1] == "D",
            "decoders": decoders,
            "can_encode": match[2] == "E",
            "encoders": encoders,
            "intra_frame_only": match[4] == "I",
            "is_lossy": match[5] == "L",
            "is_lossless": match[6] == "S",
        }
        if not encoders:
            del data[match[7]]["encoders"]
        if not decoders:
            del data[match[7]]["decoders"]

    # return all if no argument specified
    if type is None and stream_type is None:
        return data

    decoder = type is not None and type == "decoder"
    encoder = type is not None and type == "encoder"
    stype = stream_type is not None

    def pick(entry):
        return (
            (decoder and entry["can_decode"]) or (encoder and entry["can_encode"])
        ) and (stype and stream_type == entry["type"])

    return {k: v for k, v in data.items() if pick(v)}


def encoders(
    stream_type: Literal["audio", "video", "subtitle"] | None = None,
    sp_kwargs: dict[str, Any] | None = None,
):
    """get summary of FFmpeg encoders

    :param stream_type: specify stream type, defaults to None
    :type stream_type: 'audio'|'video'|'subtitle', optional
    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of encoders
    :rtype: dict

    Each key of the returned dict is a name of a decoder or encoder and its
    value is a dict with the following items:

    ================  ====  ===============================================
    Key               type  description
    ================  ====  ===============================================
    type              str   Stream type: 'audio'|'video'|'subtitle'
    description       str   Short description of the coder
    frame_mt          bool  True if employs frame-level multithreading
    slice_mt          bool  True if employs slice-level multithreading
    experimental      bool  True if experimental encoder
    draw_horiz_band   bool  True if supports draw_horiz_band
    directRendering   bool  True if supports direct encoding method 1
    ================  ====  ===============================================
    """
    return _coders("encoders", stream_type, sp_kwargs)


def decoders(
    stream_type: Literal["audio", "video", "subtitle"] | None = None,
    sp_kwargs: dict[str, Any] | None = None,
):
    """get summary of FFmpeg decoders

    :param stream_type: specify stream type, defaults to None
    :type stream_type: 'audio'|'video'|'subtitle', optional
    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of decoders or encoders
    :rtype: dict


    Each key of the returned dict is a name of a decoder and its
    value is a dict with the following items:

    ================  ====  ===============================================
    Key               type  description
    ================  ====  ===============================================
    type              str   Stream type: 'audio'|'video'|'subtitle'
    description       str   Short description of the coder
    frame_mt          bool  True if employs frame-level multithreading
    slice_mt          bool  True if employs slice-level multithreading
    experimental      bool  True if experimental encoder
    draw_horiz_band   bool  True if supports draw_horiz_band
    directRendering   bool  True if supports direct encoding method 1
    ================  ====  ===============================================
    """
    return _coders("decoders", stream_type, sp_kwargs)


def _coders(
    type,
    stream_type=None,
    sp_kwargs: dict[str, Any] | None = None,
):
    # reversed fftools/comdutils.c show_encoders()

    stdout = _run(type, sp_kwargs)
    data = {}
    for match in _coderRegexp.finditer(stdout):
        stype = {"V": "video", "A": "audio", "S": "subtitle"}[match[1]]
        data[match[7]] = {
            "type": stype,
            "description": match[8],
            "frame_mt": match[2] == "F",
            "slice_mt": match[3] == "S",
            "experimental": match[4] == "X",
            "draw_horiz_band": match[5] == "B",
            "directRendering": match[6] == "D",
        }

    if stream_type is not None:
        data = {k: v for k, v in data.items() if v["type"] == stream_type}

    return data


#   / **
#    * reversed fftools/comdutils.c show_formats()
#    * /


def formats(sp_kwargs: dict[str, Any] | None = None):
    """get FFmpeg formats

    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of formats
    :rtype: dict


    Each key of the returned dict is a name of a format and its value is a dict
    with the following items:

    ================  ====  ===============================================
    Key               type  description
    ================  ====  ===============================================
    description       str   Short description of the format
    can_demux         bool  True if supports inputs of this format
    can_mux           bool  True if support outputs of this format
    ================  ====  ===============================================
    """
    return _getFormats("formats", True, sp_kwargs)


def devices(
    type: Literal["source", "sink"] = None, sp_kwargs: dict[str, Any] | None = None
):
    """get FFmpeg devices

    :param type: specify source or sink type, defaults to None
    :type type: 'source'|'sink', optional
    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of devices
    :rtype: dict


    Each key of the returned dict is a name of a device and its value is a dict
    with the following items:

    ================  ====  ===============================================
    Key               type  description
    ================  ====  ===============================================
    description       str   Short description of the device
    can_demux         bool  True if supports inputs of this format
    can_mux           bool  True if support outputs of this format
    ================  ====  ===============================================
    """
    devs = _getFormats("devices", True, sp_kwargs)
    if type:
        try:
            key = {"source": "can_demux", "sink": "can_mux"}[type]
        except:
            raise ValueError(f'type must be either "source" or "sink"')
        return {k: v for k, v in devs.items() if v[key]}
    return devs


def muxers(sp_kwargs: dict[str, Any] | None = None):
    """get FFmpeg muxers

    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of muxers
    :rtype: dict


    Each key of the returned dict is a name of a muxer and its value is a dict
    with the following items:

    ================  ====  ===============================================
    Key               type  description
    ================  ====  ===============================================
    description       str   Short description of the muxer
    ================  ====  ===============================================
    """
    return _getFormats("muxers", False, sp_kwargs)


def demuxers(sp_kwargs: dict[str, Any] | None = None):
    """get FFmpeg demuxers

    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of demuxers
    :rtype: dict


    Each key of the returned dict is a name of a demuxer and its value is a dict
    with the following items:

    ================  ====  ===============================================
    Key               type  description
    ================  ====  ===============================================
    description       str   Short description of the demuxer
    ================  ====  ===============================================
    """
    return _getFormats("demuxers", False, sp_kwargs)


def _getFormats(type, doCan, sp_kwargs: dict[str, Any] | None = None):
    stdout = _run(type, sp_kwargs)

    data = {}
    for match in _formatRegexp.finditer(stdout):
        for format in match[3].split(","):
            if not (format in data):
                data[format] = {"description": match[4]}
            if doCan:
                data[format]["can_demux"] = match[1] == "D"
                data[format]["can_mux"] = match[2] == "E"
    return data


#   // reversed fftools/comdutils.c show_bsfs()


def bsfilters(sp_kwargs: dict[str, Any] | None = None):
    """get list of FFmpeg bitstream filters

    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of bistream filters
    :rtype: list(str)
    """
    stdout = _run("bsfs", sp_kwargs)
    m = re.match(r"\s*Bitstream filters:\s+([\s\S]+)\s*", stdout)
    return re.split(r"\s*\n\s*", m[1].strip())


#   // reversed fftools/comdutils.c show_protocols()


def protocols(sp_kwargs: dict[str, Any] | None = None):
    """get list of supported protocols

    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of protocols
    :rtype: dict

    Returned dict has 'input' and 'output' keys and each contains a list of
    supported protocol names.

    """
    stdout = _run("protocols", sp_kwargs)
    match = re.search(r"Input:\s+([\s\S]+)Output:\s+([\s\S]+)", stdout)
    return dict(
        input=re.split(r"\s*\n\s*", match[1]), output=re.split(r"\s*\n\s*", match[1])
    )


#   // according to fftools/comdutils.c show_pix_fmts()


def pix_fmts(sp_kwargs: dict[str, Any] | None = None):
    """get supported pixel formats

    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of supported pixel formats
    :rtype: dict

    Each key of the returned dict is a name of a pix_fmt and its value is a dict
    with the following items:

    ==============  ====  ===============================================
    Key             type  description
    ==============  ====  ===============================================
    nb_components   int   Number of color components
    bits_per_pixel  int   Number of bits per pixel
    input           bool  True if can be used as an input option
    output          bool  True if can be used as an output option
    hw_accel        bool  True if supported by hardware accelerators
    paletted        bool  True if uses paletted colors
    bitstream       bool  True if can be used with bistreams
    ==============  ====  ===============================================
    """
    stdout = _run("pix_fmts", sp_kwargs)

    return {
        match[6]: dict(
            nb_components=int(match[7]),
            bits_per_pixel=int(match[8]),
            input=match[1] == "I",
            output=match[2] == "O",
            hw_accel=match[3] == "H",
            paletted=match[4] == "P",
            bitstream=match[5] == "B",
        )
        for match in re.finditer(
            r"([I.])([O.])([H.])([P.])([B.])\s+(\S+)\s+(\d+)\s+(\d+)", stdout
        )
    }


def sample_fmts(sp_kwargs: dict[str, Any] | None = None):
    """get supported audio sample formats

    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of supported audio sample formats
    :rtype: dict

    Each key of the returned dict is a name of a sample_fmt and its value
    is the number of bits per sample.
    """

    #   // according to fftools/comdutils.c show_sample_fmts()
    stdout = _run("sample_fmts", sp_kwargs)
    return {match[1]: int(match[2]) for match in re.finditer(r"(\S+)\s+(\d+)", stdout)}


def layouts(sp_kwargs: dict[str, Any] | None = None):
    """get supported audio channel layouts

    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of supported audio channel layouts
    :rtype: dict

    Returned dict has two keys "channels" and "layouts". The value of "channels"
    is a dict of possible channel names as keys and their descriptions as values.
    The value of "layouts" is also a dict, which keys specifies the names and
    their value strs indicate the combinations of channels (their names are
    "+"ed).
    """

    #   // according to fftools/comdutils.c show_layouts()
    stdout = _run("layouts", sp_kwargs)
    match = re.match(
        r"\s*Individual channels:\s+NAME\s+DESCRIPTION\s+(\S[\s\S]+)Standard channel layouts:\s+NAME\s+DECOMPOSITION\s+(\S[\s\S]+)",
        stdout,
    )
    return dict(
        channels={
            m[1]: m[2] for m in re.finditer(r"(\S+)\s+\s([\s\S]+?)\s*\n", match[1])
        },
        layouts={
            m[1]: m[2] for m in re.finditer(r"(\S+)\s+(\S[\s\S]+?)\s*\n", match[2])
        },
    )


def colors(sp_kwargs: dict[str, Any] | None = None):
    """get recognized color names

    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of color names
    :rtype: dict

    The keys of the returned dict are the name of the colors and their values
    are the RGB hex strs.
    """

    #   // according to fftools/comdutils.c show_colors()
    stdout = _run("colors", sp_kwargs)
    return {
        match[1]: match[2]
        for match in re.finditer(r"(\S+)\s+(\#[0-9a-f]{6})\s*?\n", stdout)
    }


def demuxer_info(
    name: str,
    sp_kwargs: dict[str, Any] | None = None,
):
    """get detailed info of a media demuxer

    :param name: Name of the demuxer
    :type name: str
    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of features
    :rtype: dict

    The returned dict has following entries:

    ==============  =========  ================================================
    Key             type       description
    ==============  =========  ================================================
    names           list(str)  List of compatible short names
    long_name       str        Common long name
    extensions      list(str)  List of associated common extensions (w/out '.')
    options         str        Unparsed string, listing supported options
    ==============  =========  ================================================
    """

    #   // according to fftools/comdutils.c show_help_demuxer()
    stdout = _run_help("demuxer", name, sp_kwargs)

    m = re.match(
        r"Demuxer (\S+) \[([^\]]+)\]:\s*?\n(?:    Common extensions: ([^.]+)\.\s*\n)?([\s\S]*)",
        stdout,
    )

    return dict(
        names=m[1].split(","),
        long_name=m[2],
        extensions=m[3].split(",") if m[3] else [],
        options=m[4],
    )


def muxer_info(
    name: str,
    sp_kwargs: dict[str, Any] | None = None,
):
    """get detailed info of a media muxer

    :param name: Name of the muxer
    :type name: str
    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of features
    :rtype: dict

    The returned dict has following entries:

    ===============  =========  ================================================
    Key              type       description
    ===============  =========  ================================================
    names            list(str)  List of compatible short names
    long_name        str        Common long name
    extensions       list(str)  List of associated common extensions (w/out '.')
    mime_types       list(str)  List of associated MIME types
    video_codecs     list(str)  List of supported video codecs
    audio_codecs     list(str)  List of supported audio codecs
    subtitle_codecs  list(str)  List of supported subtitle codecs
    options          str        Unparsed string, listing supported options
    ===============  =========  ================================================
    """

    #   // according to fftools/comdutils.c show_help_muxer()

    stdout = _run_help("muxer", name, sp_kwargs)

    m = re.match(
        r"Muxer (\S+) \[([^\]]+)\]:\s*?\n(?:    Common extensions: ([^.]+)\.\s*?\n)?(?:    Mime type: ([^.]+)\.\s*?\n)?(?:    Default video codec: ([^.]+)\.\s*?\n)?(?:    Default audio codec: ([^.]+)\.\s*?\n)?(?:    Default subtitle codec: ([^.]+).\s*?\n)?([\s\S]*)",
        stdout,
    )

    return {
        "names": m[1].split(","),
        "long_name": m[2],
        "extensions": m[3].split(",") if m[3] else [],
        "mime_types": m[4].split(",") if m[4] else [],
        "video_codecs": m[5].split(",") if m[5] else [],
        "audio_codecs": m[6].split(",") if m[6] else [],
        "subtitle_codecs": m[7].split(",") if m[7] else [],
        "options": m[8],
    }


def encoder_info(
    name: str,
    sp_kwargs: dict[str, Any] | None = None,
):
    """get detailed info of an encoder

    :param name: Name of the encoder
    :type name: str
    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of features
    :rtype: dict

    The returned dict has following entries:

    ======================  ==============  ================================================
    Key                     type            description
    ======================  ==============  ================================================
    name                    list(str)       Short names
    long_name               str             Long name
    capabilities            list(str)       List of supported capabilities
    threading               list(str)       List of threading capabilities
    supported_hwdevices     list(str)       List of supported hardware accelerators
    supported_framerates    list(Fraction)  List of supported video frame rates
    supported_pix_fmts      list(str)       List of supported video pixel formats
    supported_sample_rates  list(int)       List of supported audio sample rates
    supported_sample_fmts   list(str)       List of supported audio sample formats
    supported_layouts       list(str)       List of supported audio channel layouts
    options                 str             Unparsed string, listing supported options
    ======================  ==============  ================================================
    """
    return _getCodecInfo(name, True, sp_kwargs)


def decoder_info(
    name: str,
    sp_kwargs: dict[str, Any] | None = None,
):
    """get detailed info of a decoder

    :param name: Name of the decoder
    :type name: str
    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of features
    :rtype: dict

    The returned dict has following entries:

    ======================  ==============  ================================================
    Key                     type            description
    ======================  ==============  ================================================
    name                    list(str)       Short names
    long_name               str             Long name
    capabilities            list(str)       List of supported capabilities
    threading               list(str)       List of threading capabilities
    supported_hwdevices     list(str)       List of supported hardware accelerators
    supported_framerates    list(Fraction)  List of supported video frame rates
    supported_pix_fmts      list(str)       List of supported video pixel formats
    supported_sample_rates  list(int)       List of supported audio sample rates
    supported_sample_fmts   list(str)       List of supported audio sample formats
    supported_layouts       list(str)       List of supported audio channel layouts
    options                 str             Unparsed string, listing supported options
    ======================  ==============  ================================================
    """
    return _getCodecInfo(name, False, sp_kwargs)


def _getCodecInfo(
    name,
    encoder,
    sp_kwargs: dict[str, Any] | None = None,
):
    #   // according to fftools/comdutils.c show_help_codec()
    stdout = _run_help("encoder" if encoder else "decoder", name, sp_kwargs)

    type = "Encoder" if encoder else "Decoder"
    m = re.search(
        type
        + r" (\S+) \[([^\]]*)\]:\s*?\n"
        + r"    General capabilities: ([^\r\n]+?)\s*?\n"
        + r"(?:    Threading capabilities: ([^\r\n]+?)\s*?\n)?"
        + r"(?:    Supported hardware devices: ([^\r\n]*?)\s*?\n)?"
        + r"(?:    Supported framerates: ([^\r\n]+?)\s*?\n)?"
        + r"(?:    Supported pixel formats: ([^\r\n]+?)\s*?\n)?"
        + r"(?:    Supported sample rates: ([^\r\n]+?)\s*?\n)?"
        + r"(?:    Supported sample formats: ([^\r\n]+?)\s*?\n)?"
        + r"(?:    Supported channel layouts: ([^\r\n]+?)\s*?\n)?"
        + r"([\s\S]*)",
        stdout,
    )

    def resolveFs(s):
        m = re.match(r"(\d+)\/(\d+)", s)
        return fractions.Fraction(int(m[1]), int(m[2]))

    _re_layouts = re.compile(
        re.sub(r"([().])", r"\\\1", "|".join(layouts()["layouts"]))
        + r"|\d+ channels \(.+?\)"
    )

    return {
        "name": m[1],
        "long_name": m[2],
        "capabilities": m[3].split(" ") if m[3] and m[3] != "none" else [],
        "threading": m[4].split(" and ") if m[4] and m[4] != "none" else [],
        "supported_hwdevices": m[5].split(" ") if m[5] else [],
        "supported_framerates": [resolveFs(s) for s in m[6].split(" ")] if m[6] else [],
        "supported_pix_fmts": m[7].split(" ") if m[7] else [],
        "supported_sample_rates": [int(v) for v in m[8].split(" ")] if m[8] else [],
        "supported_sample_fmts": m[9].split(" ") if m[9] else [],
        "supported_layouts": _re_layouts.findall(m[10]) if m[10] else [],
        "options": m[11],
    }


# fmt: off
FilterInfo = namedtuple(
    "FilterInfo",
    [ "name", "description", "threading", "inputs", "outputs",
      "options", "extra_options", "timeline_support",
    ],
)
FilterOption = namedtuple(
    "FilterOption",
    ["name", "aliases", "type", "help", "ranges", "constants", "default", 
     "video", "audio", "runtime"],
)
# fmt:on


def _get_filter_pad_info(str):
    if str.startswith("        dynamic"):
        return None
    elif str.startswith("        none"):
        return []

    matches = re.finditer(r"       #\d+: (\S+)(?= \() \((\S+)\)\s*?(?:\n|$)", str)
    if not matches:
        raise Exception("Failed to parse filter port info: %s" % str)
    return [{"name": m[1], "type": m[2]} for m in matches]


def _conv_func(type, s):
    try:
        return type(s)
    except:
        return s


def _get_filter_option_constant(str):
    m = re.match(
        r"     ([^ \n]+) {1,16}(?:([^ ]+) {1,12}| {13})"
        r"[.E][.D][.F][.V][.A][.S][.X][.R][.B][.T][.P]"
        r"(?: (.+))?\n?",
        str,
    )
    return m[1], (m[2] and int(m[2]), m[3] or "")


def _get_filter_option(str, name):
    # libavutil/opt.c/opt_list
    lines = str.splitlines()

    # first line is the main option definition
    m0 = re.match(
        r"  (?: |-)?([^ \n]+) {1,17}(?:\<([^ >]+)\> {1,12}| {13})"
        r"[.E][.D][.F]([.V])([.A])[.S][.X][.R][.B]([.T])[.P]",
        lines[0],
    )
    if not m0:
        # likely deprecated
        logger.info(
            f"_get_filter_option(): invalid option line found for {name} filter. Likely deprecated:\n{lines[0]}"
        )
        return None
    name, type, *flags = m0.groups()

    m1 = re.search(r"( \(from \S+? to \S+?\))*(?: \(default (.+)\))?$", lines[0])
    ranges_str, default = m1.groups()

    help = lines[0][m0.end() + 1 : m1.start()]

    if default:
        if type == "string":
            # remove quotes
            default = default[1:-1]
        elif type == "boolean":
            default = {"true": True, "false": False}.get(default, default)

    conv = (
        partial(_conv_func, int)
        if type in ("int", "int64", "uint64")
        else (
            partial(_conv_func, float)
            if type in ("float", "double")
            else partial(_conv_func, Fraction) if type == "rational" else (lambda s: s)
        )
    )

    ranges = (
        None
        if ranges_str is None
        else [
            (conv(m[1]), conv(m[2]))
            for m in re.finditer(r"\(from (\S+?) to (\S+?)\)", ranges_str)
        ]
    )

    constants = [_get_filter_option_constant(l) for l in lines[1:] if l]

    if len(constants):
        # combines aliases
        def chk_is_alias(i, o):
            other = constants[i]
            return other[1] == o[1]

        has_alias = [chk_is_alias(i, o) for i, o in enumerate(constants[1:])]
        has_alias.append(False)
        for i, has in enumerate(has_alias):
            k, v = constants[i]
            constants[i] = (k, (constants[i + 1][0] if has else None, *v))

        has_alias.insert(0, False)
        constants = [o for o, isa in zip(constants, has_alias[:-1]) if not isa]

    return FilterOption(
        name,
        [],
        type,
        help,
        ranges,
        dict(constants),
        conv(default),
        *(fl != "." for fl in flags),
    )


def _get_filter_options(str):
    m = re.match(r"(.+)? AVOptions:\n", str)
    name = m[1]
    blocks = re.split(r"\n(?!     |\n|$)", str[m.end() :])
    opts = [_get_filter_option(line, name) for line in blocks if line]

    # combines aliases
    def is_alias(i, o):
        other = opts[i]
        return other.type == o.type and other.help == o.help

    n = len(opts)
    i = 0
    alias_of = [-1] * n
    for j, o in enumerate(opts[1:]):
        if is_alias(i, o):
            alias_of[j + 1] = i
        else:
            i = j + 1

    im = [*[i for i, j in enumerate(alias_of) if j < 0], n]

    for i0, i1 in zip(im[:-1], im[1:]):
        if i1 - i0 > 1:
            v = list(opts[i0])
            v[1] = [o.name for o in opts[i0 + 1 : i1]]
            opts[i0] = FilterOption(*v)

    opts = [o for o, isa in zip(opts, alias_of) if isa < 0]

    return name, opts


def filter_info(
    name: str,
    sp_kwargs: dict[str, Any] | None = None,
):
    """get detailed info of a filter

    :param name: Name of the filter
    :type name: str
    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of features
    :rtype: FilterInfo (namedtuple)

    The returned FilterInfo named tuple has following entries:

    ================ ============================  ================================================
    Key              type                          description
    ================ ============================  ================================================
    name             str                           Name
    description      str                           Description
    threading        list(str)                     List of threading capabilities
    inputs           list(dict)|str                List of input pads or 'dynamic' if variable
    outputs          list(dict)|str                List of output pads or 'dynamic' if variable
    options          list(FilterOption)            List of filter options
    extra_options    dict(str,list(FilterOption))  Extra options co-listed
    timeline_support bool                          True if `enable` timeline option is supported
    ================ ============================  ================================================

    'inputs' and 'outputs' entries has two keys: 'name' and 'type'
    defining the pad name and pad stream type ('audio' or 'video')

    FilterOption is a namedtuple with the following entries:

    =========  ===========================  ================================================
    Key        type                         description
    =========  ===========================  ================================================
    name       str                          Name
    alias      str                          Alias name
    type       str                          Data type
    help       str                          Help text
    ranges     list(tuple(any,any))|None    List of ranges of values
    constants  dict(str:any)                List of defined constant/enum values
    default    any                          Default value
    video      bool                         True if option for video stream
    audio      bool                         True if option for audio stream
    runtime    bool                         True if modifiable during runtime
    =========  ===========================  ================================================

    """

    #   // according to fftools/comdutils.c show_help_filter()
    stdout = _run_help("filter", name, sp_kwargs)

    blocks = re.split(r"\n(?! |\n|$)", stdout)

    m = re.match(
        r"Filter (\S+)\s*?\n"
        r"(?:  (.+?)\s*?\n)?"
        r"(?:    (slice threading supported)\s*?\n)?"
        r"    Inputs:\n"
        r"([\s\S]*)"
        r"    Outputs:\n"
        r"([\s\S]*)",
        blocks[0],
    )
    name = m[1]
    desc = m[2]
    threading = ["slice"] if m[3] else []
    inputs = _get_filter_pad_info(m[4])
    outputs = _get_filter_pad_info(m[5])
    timeline = (
        blocks[-1].rstrip()
        == "This filter has support for timeline through the 'enable' option."
    )

    extra_options = dict(
        (_get_filter_options(b) for b in (blocks[1:-1] if timeline else blocks[1:]))
    )

    options = extra_options.pop(name, None)
    if options is None and len(extra_options):
        opt_name = next(
            (
                o_name
                for o_name in extra_options.keys()
                # if (o_name == f"(a){name}")
                # or (name[0] == "a" and o_name == f"(a){name[1:]}")
                # or re.match(o_name, name)
                # or re.search(rf"(?:^|[^a-z]){name}($|[^a-z])", o_name)
                # or (name == "highshelf" and o_name == "treble/high/tiltshelf")
                # or (name == "chromakey_cuda" and o_name == "cudachromakey")
                # or (name == "hwupload_cuda" and o_name == "cudaupload")
            ),
            None,
        )
        if opt_name:
            options = extra_options.pop(opt_name)
        elif len(extra_options) == 1:
            o_name, options = extra_options.popitem()
            logger.info(f"filter_info({name}): assigned mismatched AVOptions {o_name}.")
        else:
            logger.warning(
                f"filter_info({name}): none of the AVOption sets appears to be the main option set:\n   {[k for k in extra_options]}"
            )

    return FilterInfo(
        name,
        desc,
        threading,
        inputs,
        outputs,
        options,
        extra_options,
        timeline,
    )


def bsfilter_info(
    name,
    sp_kwargs: dict[str, Any] | None = None,
):
    """get detailed info of a bitstream filter

    :param name: Name of the bitstream filter
    :type name: str
    :param sp_kwargs: Additional keyword arguments for :py:func:`subprocess.run`,
                      default to None
    :type sp_kwargs: dict[str, Any], optional
    :return: list of features
    :rtype: dict

    The returned dict has following entries:

    ================  ==============  ================================================
    Key               type            description
    ================  ==============  ================================================
    name              str             Name
    supported_codecs  str             List of supported codecs
    options           str             Unparsed string, listing supported options
    ================  ==============  ================================================

    """

    #   // according to fftools/comdutils.c show_help_bsf()
    stdout = _run_help("bsf", name, sp_kwargs)

    m = re.match(
        r"Bit stream filter (\S+)\s*?\n"
        r"(?:    Supported codecs: ([^\r\n]+?)\s*?\n)?"
        r"([\s\S]*)",
        stdout,
    )

    if stdout.startswith("Unknown"):
        raise Exception(stdout)

    return {
        "name": m[1],
        "supported_codecs": m[2].split(" ") if m[2] else [],
        "options": m[3],
    }


#:dict: list of video size presets with their sizes
video_size_presets = {
    "ntsc": (720, 480),
    "pal": (720, 576),
    "qntsc": (352, 240),
    "qpal": (352, 288),
    "sntsc": (640, 480),
    "spal": (768, 576),
    "film": (352, 240),
    "ntsc-film": (352, 240),
    "sqcif": (128, 96),
    "qcif": (176, 144),
    "cif": (352, 288),
    "4cif": (704, 576),
    "16cif": (1408, 1152),
    "qqvga": (160, 120),
    "qvga": (320, 240),
    "vga": (640, 480),
    "svga": (800, 600),
    "xga": (1024, 768),
    "uxga": (1600, 1200),
    "qxga": (2048, 1536),
    "sxga": (1280, 1024),
    "qsxga": (2560, 2048),
    "hsxga": (5120, 4096),
    "wvga": (852, 480),
    "wxga": (1366, 768),
    "wsxga": (1600, 1024),
    "wuxga": (1920, 1200),
    "woxga": (2560, 1600),
    "wqsxga": (3200, 2048),
    "wquxga": (3840, 2400),
    "whsxga": (6400, 4096),
    "whuxga": (7680, 4800),
    "cga": (320, 200),
    "ega": (640, 350),
    "hd480": (852, 480),
    "hd720": (1280, 720),
    "hd1080": (1920, 1080),
    "2k": (2048, 1080),
    "2kflat": (1998, 1080),
    "2kscope": (2048, 858),
    "4k": (4096, 2160),
    "4kflat": (3996, 2160),
    "4kscope": (4096, 1716),
    "nhd": (640, 360),
    "hqvga": (240, 160),
    "wqvga": (400, 240),
    "fwqvga": (432, 240),
    "hvga": (480, 320),
    "qhd": (960, 540),
    "2kdci": (2048, 1080),
    "4kdci": (4096, 2160),
    "uhd2160": (3840, 2160),
    "uhd4320": (7680, 4320),
}

#:dict: list of video frame rate presets with their rates
frame_rate_presets = {
    "ntsc": fractions.Fraction(30000, 1001),
    "pal": fractions.Fraction(25, 1),
    "qntsc": fractions.Fraction(30000, 1001),
    "qpal": fractions.Fraction(25, 1),
    "sntsc": fractions.Fraction(30000, 1001),
    "spal": fractions.Fraction(25, 1),
    "film": fractions.Fraction(24, 1),
    "ntsc-film": fractions.Fraction(24000, 1001),
}
