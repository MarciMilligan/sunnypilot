"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

import ctypes
import sys
from collections.abc import Buffer
from pathlib import Path

import numpy as np

from openpilot.system.camerad.cameras.nv12_info import get_nv12_info

SOURCE_SIZE = (1928, 1208)
TARGET_SIZE = (1344, 760)


class FrameResize:
  """Fixed NV12 point sampling: floor(dst * source / target), with edge-filled padding."""

  def __init__(self):
    source_stride, source_y_height, source_uv_height, _ = get_nv12_info(*SOURCE_SIZE)
    target_stride, target_y_height, target_uv_height, _ = get_nv12_info(*TARGET_SIZE)
    self.source_copy_size = source_stride * (source_y_height + source_uv_height)
    self.target_copy_size = target_stride * (target_y_height + target_uv_height)
    suffix = ".dylib" if sys.platform == "darwin" else ".so"
    self._lib = ctypes.CDLL(Path(__file__).with_name(f"libframe_resize{suffix}"))
    self._resize = self._lib.frame_resize_nv12
    self._resize.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
    self._resize.restype = ctypes.c_int

  def resize(self, source: Buffer, destination: np.ndarray) -> None:
    """Write into a contiguous uint8 frame view of target_copy_size bytes."""
    frame = np.frombuffer(source, dtype=np.uint8, count=self.source_copy_size)
    if (destination.dtype != np.uint8 or destination.ndim != 1 or destination.size != self.target_copy_size
        or not destination.flags.c_contiguous or not destination.flags.writeable):
      raise ValueError(f"NV12 resize destination must be a writable contiguous uint8 vector of {self.target_copy_size} bytes")
    if self._resize(frame.ctypes.data, frame.nbytes, destination.ctypes.data, destination.nbytes) != 0:
      raise ValueError("Native NV12 resize rejected invalid or overlapping buffers")
