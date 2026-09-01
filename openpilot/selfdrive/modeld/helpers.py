import io
import json
import math
import os
import pickle
import shutil
import struct
import tempfile
from pathlib import Path

from openpilot.common.file_chunker import get_manifest_path
from openpilot.common.hardware.usb import CHESTNUT_USB_PRODUCT, USB_DEVICES_PATH, is_chestnut_usb_id

MODELS_DIR = Path(__file__).resolve().parent / 'models'
TG_INPUT_DEVICES_PATH = MODELS_DIR / 'tg_input_devices.json'
CHESTNUT_POWERED_VOLTAGE = 5000
CHESTNUT_PCIE_READY = 0x78


def get_tg_input_devices(process_name: str, chestnut: bool):
  with open(TG_INPUT_DEVICES_PATH) as f:
    return json.load(f)[process_name]['default' if not chestnut else 'chestnut']

def modeld_pkl_path(chestnut: bool):
  prefix = 'big_' if chestnut else ''
  return MODELS_DIR / f'{prefix}driving_tinygrad.pkl'

def dump_oob(obj, f):
  with tempfile.TemporaryFile(dir=".") as tmp:
    def buffer_callback(pb: pickle.PickleBuffer):
      m = pb.raw()
      tmp.write(struct.pack('<q', m.nbytes))
      tmp.write(m)
      pb.release() # keep peak ram at ~1 buffer
    stream = io.BytesIO()
    pickle.Pickler(stream, protocol=5, buffer_callback=buffer_callback).dump(obj)
    opcodes = stream.getvalue()
    f.write(struct.pack('<q', len(opcodes)))
    f.write(opcodes)
    tmp.seek(0)
    shutil.copyfileobj(tmp, f)

def load_oob(f):
  opcodes = f.read(struct.unpack('<q', f.read(8))[0])
  def buffers():
    while (h := f.read(8)):
      pb = pickle.PickleBuffer(bytearray(struct.unpack('<q', h)[0]))
      f.readinto(pb)
      yield pb
  return pickle.load(io.BytesIO(opcodes), buffers=buffers())

def chestnut_present() -> bool:
  for d in USB_DEVICES_PATH.glob("*"):
    try:
      usb_id = (int((d / "idVendor").read_text(), 16), int((d / "idProduct").read_text(), 16))
      product = (d / "product").read_text().strip()
      if is_chestnut_usb_id(*usb_id) and product == CHESTNUT_USB_PRODUCT:
        return True
    except Exception:
      pass
  return False

def chestnut_compiled() -> bool:
  return Path(get_manifest_path(modeld_pkl_path(chestnut=True))).is_file()


def chestnut_ready(state) -> bool:
  return state.supplyVoltage >= CHESTNUT_POWERED_VOLTAGE and not state.supplyFault and state.pcieLtssm == CHESTNUT_PCIE_READY


def apply_chestnut_power_limit() -> float:
  """Configure tinygrad's eGPU power cap before the AMD device is opened."""
  # imported lazily: this module is imported by SConscript before libparams_c is built
  from openpilot.common.params import Params

  params = Params()
  configured_power_limit = os.getenv("AM_POWER_LIMIT") or params.get("ChestnutPowerLimitW")

  try:
    power_limit_watts = float(configured_power_limit)
  except (TypeError, ValueError):
    power_limit_watts = 0.0
  if not math.isfinite(power_limit_watts) or power_limit_watts < 0:
    power_limit_watts = 0.0

  gpu_was_power_limited = params.get("ChestnutPowerLimitActive")

  if power_limit_watts > 0:
    os.environ["AM_POWER_LIMIT"] = str(power_limit_watts)
    if gpu_was_power_limited is not True:
      params.put_bool("ChestnutPowerLimitActive", True, block=True)
  else:
    os.environ.pop("AM_POWER_LIMIT", None)
    # A partial tinygrad boot keeps the previous SMU limit, so force a full reset.
    if gpu_was_power_limited is not False:
      os.environ["AM_RESET"] = "1"
  return power_limit_watts


def confirm_chestnut_power_limit_reset(power_limit_watts: float) -> None:
  if power_limit_watts > 0:
    return

  from openpilot.common.params import Params

  Params().put_bool("ChestnutPowerLimitActive", False, block=True)
