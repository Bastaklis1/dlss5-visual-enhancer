from __future__ import annotations

from fractions import Fraction

import av
import numpy as np


class PipeWriter:
    """Expose only the write operations libavformat needs for a pipe."""

    def __init__(self, stream) -> None:
        self.stream = stream

    def write(self, data) -> int:
        return self.stream.write(data)

    def flush(self) -> None:
        self.stream.flush()


class RawVideoPacketMuxer:
    """Write raw video frames into NUT without constructing/encoding VideoFrame objects.

    The packet payload references the caller-provided ndarray only for the duration of
    ``write``.  Once ``container.mux`` returns the caller may safely reuse the buffer.
    """

    def __init__(
        self,
        pipe,
        *,
        width: int,
        height: int,
        rate: Fraction,
        time_base: Fraction,
        pix_fmt: str = "rgba",
    ) -> None:
        self.time_base = time_base
        self.container = av.open(
            PipeWriter(pipe), mode="w", format="nut", options={"write_index": "0"}
        )
        self.stream = self.container.add_stream("rawvideo", rate=rate)
        self.stream.width = width
        self.stream.height = height
        self.stream.pix_fmt = pix_fmt
        if pix_fmt == "rgba":
            self.stream.codec_context.codec_tag = "RGBA"
        self.stream.time_base = time_base
        self.stream.codec_context.time_base = time_base
        self.container.start_encoding()

    def write(self, frame: np.ndarray, pts: int, duration: int = 0) -> None:
        if not frame.flags.c_contiguous:
            raise ValueError("Raw NUT frame must be C-contiguous.")
        packet = av.Packet(memoryview(frame).cast("B"))
        packet.stream = self.stream
        packet.pts = packet.dts = int(pts)
        packet.duration = int(duration)
        packet.time_base = self.time_base
        packet.is_keyframe = True
        self.container.mux(packet)

    def close(self) -> None:
        self.container.close()
