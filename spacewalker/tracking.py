"""Runtime binding to VITURE's current libglasses C ABI (Gen1/Gen2)."""
import ctypes as C
import os
import platform
from pathlib import Path
import threading
import time
from .geometry import IDENTITY, conjugate, matrix, multiply, normalize, viture_euler_to_gl, slerp

POSE_CALLBACK = C.CFUNCTYPE(None, C.POINTER(C.c_float), C.c_uint64)
STATE_CALLBACK = C.CFUNCTYPE(None, C.c_int, C.c_int)


def devices(root=Path('/sys/bus/usb/devices')):
    result = set()
    for p in root.glob('*/idVendor'):
        try:
            if p.read_text().strip().lower() == '35ca':
                result.add(int((p.parent/'idProduct').read_text().strip(), 16))
        except (OSError, ValueError):
            pass
    return sorted(result)


def library_path(explicit=None):
    if explicit or os.environ.get('VITURE_SDK_LIBRARY'):
        p = Path(explicit or os.environ['VITURE_SDK_LIBRARY']).expanduser()
        if not p.is_file():
            raise RuntimeError(f'SDK library does not exist: {p}')
        return str(p.resolve())
    local = Path(__file__).resolve().parent.parent/'vendor'
    candidates = list(local.glob('**/libglasses.so'))
    machine = {'x86_64':62, 'aarch64':183}.get(platform.machine())
    if machine is not None:
        compatible = []
        for candidate in candidates:
            try:
                with candidate.open('rb') as stream:
                    header = stream.read(20)
            except OSError:
                continue
            if (len(header)==20 and header[:5]==b'\x7fELF\x02' and header[5] in (1,2)
                    and int.from_bytes(header[18:20], 'little' if header[5]==1 else 'big')==machine):
                compatible.append(candidate)
        candidates = compatible
    if len(candidates) == 1:
        return str(candidates[0])
    raise RuntimeError('Select the current VITURE Linux SDK libglasses.so in Tracking settings. '
                       'Download it from viture.com/developer; the old libviture SDK does not support Pro 2.')


class PoseState:
    def __init__(self):
        self.lock = threading.Lock()
        self.raw = IDENTITY.copy()
        self.center = None
        self._reference_up = (0., 1., 0.)
        self.filtered = IDENTITY.copy()
        self.received = 0.
        self.sample_received = 0.
        self.last_render = time.monotonic()
        self.samples = 0

    def push(self, q):
        q = normalize(q)
        with self.lock:
            self.raw = q
            if self.center is None:
                self._center_on(q)
            self.received = time.monotonic()
            self.samples += 1

    def recenter(self):
        with self.lock:
            self._center_on(self.raw if self.received else None)
            self.filtered = IDENTITY.copy()

    def _center_on(self, q):
        # Called with the pose lock held. Keep gravity in the same reference
        # frame as the recentered pose; its Y axis can be pitched or rolled.
        self.center = conjugate(q) if q is not None else None
        self._reference_up = tuple(float(v) for v in matrix(self.center)[:,1]) if q is not None else (0., 1., 0.)

    @property
    def reference_up(self):
        with self.lock:
            return self._reference_up

    def orientation(self, smoothing_ms=0.):
        now = time.monotonic()
        with self.lock:
            target = multiply(self.center, self.raw) if self.center is not None else IDENTITY.copy()
            self.sample_received = self.received
        if smoothing_ms <= 0:
            self.last_render = now
            self.filtered = target
            return target.copy()
        dt, self.last_render = max(0, now-self.last_render), now
        import math
        weight = 1-math.exp(-dt/(smoothing_ms/1000)) if smoothing_ms > 0 else 1.
        self.filtered = slerp(self.filtered, target, weight)
        return self.filtered.copy()

    @property
    def age(self):
        with self.lock:
            return time.monotonic()-self.received if self.received else float('inf')

    def snapshot(self):
        """Read the latest recentered pose without advancing render smoothing."""
        with self.lock:
            q = multiply(self.center,self.raw) if self.center is not None else IDENTITY.copy()
            age = time.monotonic()-self.received if self.received else None
            return q,age


class VitureTracker:
    def __init__(self, library=None, pid=None, loader=C.CDLL):
        self.pose = PoseState()
        self.handle = None
        self.initialized = self.started = self.streaming = False
        self.original_display_mode = None
        self.lib = loader(library_path(library))
        self._bind()
        self.lib.xr_device_provider_set_log_level(1)
        candidates = [pid] if pid is not None else devices()
        valid = [p for p in candidates if self.lib.xr_device_provider_is_product_id_valid(p) == 1]
        if not valid:
            raise RuntimeError('No supported VITURE USB device found. Connect the glasses with USB data.')
        self.pid = valid[0]
        self.callback = POSE_CALLBACK(self._on_pose)  # Keep alive until destroy has joined SDK threads.
        self.state_callback = STATE_CALLBACK(lambda state, value: None)

    def _bind(self):
        signatures = {
            'set_log_level': ([C.c_int], None),
            'is_product_id_valid': ([C.c_int], C.c_int),
            'is_product_support_imu_frequency': ([C.c_int, C.c_int, C.c_int], C.c_int),
            'create': ([C.c_int], C.c_void_p),
            'get_device_type': ([C.c_void_p], C.c_int),
            'initialize': ([C.c_void_p, C.c_char_p, C.c_char_p], C.c_int),
            'start': ([C.c_void_p], C.c_int),
            'stop': ([C.c_void_p], C.c_int),
            'shutdown': ([C.c_void_p], C.c_int),
            'destroy': ([C.c_void_p], None),
            'register_imu_pose_callback': ([C.c_void_p, POSE_CALLBACK], C.c_int),
            'register_state_callback': ([C.c_void_p, STATE_CALLBACK], C.c_int),
            'open_imu': ([C.c_void_p, C.c_uint8, C.c_uint8], C.c_int),
            'close_imu': ([C.c_void_p, C.c_uint8], C.c_int),
            'get_display_mode': ([C.c_void_p], C.c_int),
            'set_display_mode': ([C.c_void_p, C.c_int], C.c_int),
        }
        try:
            for name, (args, result) in signatures.items():
                fn = getattr(self.lib, 'xr_device_provider_'+name)
                fn.argtypes, fn.restype = args, result
        except AttributeError as e:
            raise RuntimeError('SDK ABI mismatch. Use the current VITURE Linux libglasses SDK.') from e

    def _call(self, name, *args):
        result = getattr(self.lib, 'xr_device_provider_'+name)(self.handle, *args)
        if result is not None and result < 0:
            raise RuntimeError(f'VITURE {name} failed ({result}). Check the udev rule, USB data cable, '
                               'and close other XR drivers before retrying.')
        return result

    def _on_pose(self, data, timestamp):
        try:
            # Follow the supplied SDK demo's Gen1/Gen2 path. The Pro 2 quaternion
            # channels have a different basis/reference from the documented NWU angles.
            self.pose.push(viture_euler_to_gl(data[0],data[1],data[2]))
        except (ValueError, IndexError):
            pass  # Drop invalid SDK packets without raising through the C callback.

    def start(self):
        try:
            self.handle = self.lib.xr_device_provider_create(self.pid)
            if not self.handle:
                raise RuntimeError('Cannot open VITURE HID device. Install packaging/70-viture.rules '
                                   'and reconnect the glasses. Do not run the viewer as root.')
            if self._call('get_device_type') not in (0, 1):
                raise RuntimeError('This tracking backend supports Gen1/Gen2 (including Pro 2); not Luma Ultra.')
            self._call('register_imu_pose_callback', self.callback)
            self._call('register_state_callback', self.state_callback)
            self._call('initialize', None, None)
            self.initialized = True
            self._call('start')
            self.started = True
            frequencies = [f for f in (4, 3, 2, 1, 0)
                           if self.lib.xr_device_provider_is_product_support_imu_frequency(self.pid, 1, f) == 1]
            if not frequencies:
                raise RuntimeError('This SDK/device combination exposes no supported pose frequency.')
            self.frequency = frequencies[0]
            self._call('open_imu', 1, self.frequency)  # Device capability table selects pose rate.
            self.streaming = True
        except Exception:
            self.close()
            raise

    def set_stereo(self, enabled):
        if not self.started:
            raise RuntimeError('Connect tracking before switching the glasses display mode.')
        if enabled:
            if self.original_display_mode is None:
                self.original_display_mode = self._call('get_display_mode')
            self._set_display_mode(0x32)  # 3840x1080 @ 60 Hz; SDK standard SBS mode.
        elif self.original_display_mode is not None:
            self._set_display_mode(self.original_display_mode)
            self.original_display_mode = None

    def _set_display_mode(self, mode):
        self._call('set_display_mode', mode)
        # Command ACK precedes the physical display reconfiguration on Gen2.
        deadline = time.monotonic()+4
        while time.monotonic() < deadline:
            if self._call('get_display_mode') == mode:
                return
            time.sleep(.2)
        raise RuntimeError('The glasses acknowledged the switch but did not report the requested display mode. '
                           'Use their physical 3D switch, then select SBS output and a 3840 × 1080 display.')

    def close(self):
        errors = []
        if self.handle:
            if self.original_display_mode is not None:
                try:
                    self.set_stereo(False)
                except RuntimeError as e:
                    errors.append(str(e))
            for active, name, args in [(self.streaming, 'close_imu', (1,)),
                                        (self.started, 'stop', ()), (self.initialized, 'shutdown', ())]:
                if active:
                    try:
                        self._call(name, *args)
                    except RuntimeError as e:
                        errors.append(str(e))
            self.lib.xr_device_provider_destroy(self.handle)
        self.handle = None
        self.initialized = self.started = self.streaming = False
        return errors
