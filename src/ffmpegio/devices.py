"""I/O Device Enumeration Module

This module allows input and output hardware devices to be enumerated in the same fashion as the 
streams of media containers. For example, instead of specifying DirectShow hardware by

```
url = 'video="WebCam":audio="Microphone"'
```

You can specify them as

```
url = 'v:0|a:0'
```


"""
import logging
from ffmpegio.path import _exec
from subprocess import PIPE, DEVNULL
from . import plugins
import re

SOURCES = {}
SINKS = {}


def scan():
    """scans the system for input/output hardware

    This function must be called by user to enable device enumeration in
    ffmpegio. Also, none of functions in `ffmpegio.devices` module will return
    meaningful outputs until `scan` is called. Likewise, `scan()` must
    run again after a change in hardware to reflect the change.

    The devices are enumerated according to the outputs of outputs
    `ffmpeg -sources` and `ffmpeg -sinks` calls for the devices supporting
    this fairly new FFmpeg interface. Additional hardware configurations
    are detected by registered plugins with hooks `device_source_api` or
    `device_sink_api`.

    Currently Supported Devices
    ---------------------------
    Windows: dshow
    Mac: tbd
    Linux: tbd
    """

    global SOURCES, SINKS

    def get_devices(dev_type):
        out = _exec(
            f"-{dev_type}",
            stderr=DEVNULL,
            stdout=PIPE,
            universal_newlines=True,
        )

        logging.debug(f"ffmpeg -{dev_type}")
        logging.debug(out.stdout)

        src_spans = [
            [m[1], *m.span()]
            for m in re.finditer(fr"Auto-detected {dev_type} for (.+?):\n", out.stdout)
        ]
        for i in range(len(src_spans) - 1):
            src_spans[i][1] = src_spans[i][2]
            src_spans[i][2] = src_spans[i + 1][1]
        src_spans[-1][1] = src_spans[-1][2]
        src_spans[-1][2] = len(out.stdout)

        def parse(log):
            # undoing print_device_list() in fftools/cmdutils.c
            if log.startswith(f"Cannot list {dev_type}"):
                return None
            devices = {}
            counts = {"audio": 0, "video": 0}
            for m in re.finditer(r"([ *]) (.+?) \[(.+?)\] \((.+?)\)\n", log):
                info = {
                    "name": m[2],
                    "description": m[3],
                    "is_default": m[1] == "*" or None,
                }
                media_types = m[4].split(",")
                for media_type in media_types:
                    if media_type in ("video", "audio"):
                        spec = f"{media_type[0]}:{counts[media_type]}"
                        counts[media_type] += 1
                        devices[spec] = {**info, "media_type": media_type}
            return devices

        return [(name, parse(out.stdout[i0:i1])) for name, i0, i1 in src_spans]

    def gather_device_info(dev_type, hook):
        plugin_devices = {
            name: api for name, api in getattr(plugins.get_hook(), hook)()
        }
        devs = {}
        for key, devlist in get_devices(dev_type):
            names = key.split(",")  # may have alias

            name = names[0]  # plugin must be defined for the base name
            if name in plugin_devices:
                info = plugin_devices[name]
                if devlist is not None:
                    info["list"] = devlist
                elif "scan" in info:
                    info["list"] = info["scan"]()
            else:
                info = {"list": devlist} if devlist else None

            if info is not None:
                for name in names:
                    devs[name] = info
        return devs

    SOURCES = gather_device_info("sources", "device_source_api")
    SINKS = gather_device_info("sinks", "device_sink_api")


def _list_devices(devs, mtype):
    return [
        dev
        for dev, info in devs.items()
        if "list" in info and any((k.startswith(mtype) for k in info["list"].keys()))
    ]


def list_video_sources():
    """list detected video source devices

    :return: list of devices
    :rtype: list[str]
    """    
    return _list_devices(SOURCES, "v")


def list_audio_sources():
    """list detected audio source devices

    :return: list of devices
    :rtype: list[str]
    """    
    return _list_devices(SOURCES, "a")


def list_video_sinks():
    """list detected video sink devices

    :return: list of devices
    :rtype: list[str]
    """    
    return _list_devices(SINKS, "v")


def list_audio_sinks():
    """list detected audio sink devices

    :return: list of devices
    :rtype: list[str]
    """    
    return _list_devices(SINKS, "a")


def _get_dev(device, dev_type):
    try:
        devices = dev_type and {"source": SOURCES, "sink": SINKS}[dev_type]
    except:
        raise ValueError(f'Unknown dev_type: {dev_type} (must be "source" or "sink") ')

    try:
        if devices:
            return devices[device]
        else:
            try:
                return SOURCES[device]
            except:
                return SINKS[device]
    except:
        raise ValueError(f"Unknown/unenumerated device: {device}")


def list_hardware(device, dev_type=None):
    """list detected hardware of a device

    :param device: name of the device
    :type device: str
    :param dev_type: source or sink, defaults to None to list all
    :type dev_type: str, optional
    :return: list of discoveredhardware
    :rtype: list[dict[str,dict]]
    """    
    return _get_dev(device, dev_type)["list"]


def list_source_options(device, enum):
    """list supported options of enumerated source hardware

    :param device: device name
    :type device: str
    :param enum: hardware specifier, e.g., v:0, a:0
    :type enum: str
    :return: list of supported option combinations. If option values are tuple
             it indicates the min and max range of the option value.
    :rtype: list[dict]
    """    
    info = _get_dev(device, "source")
    try:
        list_options = info["list_options"]
    except:
        raise ValueError(f"No options to list")
    return list_options('source', enum)


def list_sink_options(device, enum):
    """list supported options of enumerated sink hardware

    :param device: device name
    :type device: str
    :param enum: hardware specifier, e.g., v:0, a:0
    :type enum: str
    :return: list of supported option combinations. If option values are tuple
             it indicates the min and max range of the option value.
    :rtype: list[dict]
    """    
    info = _get_dev(device, "sink")
    try:
        list_options = info["list_options"]
    except:
        raise ValueError(f"No options to list")
    return list_options('sink', enum)


def resolve_source(url, opts):
    """resolve source enumeration

    :param url: input url, possibly device enum
    :type url: str
    :param opts: input options
    :type opts: dict
    :return: possibly modified url and opts
    :rtype: tuple[str,dict]

    This function is called by `ffmpeg.compose()` to convert
    device enumeration back to url expected by ffmpeg

    """
    try:
        dev = SOURCES[opts["f"]]
        assert dev is not None
    except:
        # not a device or unknown device
        return url, opts

    try:
        return dev["resolve"]("source", url), opts
    except:
        try:
            url = dev["list"][url]
        finally:
            return url, opts


def resolve_sink(url, opts):
    """resolve sink enumeration

    :param url: output url, possibly device enum
    :type url: str
    :param opts: output options
    :type opts: dict
    :return: possibly modified url and opts
    :rtype: tuple[str,dict]

    This function is called by `ffmpeg.compose()` to convert
    device enumeration back to url expected by ffmpeg

    """
    try:
        dev = SINKS[opts["f"]]
        assert dev is not None
    except:
        # not a device or unknown device
        return url, opts

    try:
        return dev["resolve"]("sink", url), opts
    except:
        try:
            url = dev["list"][url]
        finally:
            return url, opts
