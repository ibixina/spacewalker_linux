"""Shared, testable coordinate conventions for rendering and pointer projection.

Quaternions use (w, x, y, z); world axes are OpenGL right/up/backward.
Textures have their first row at v=0, including desktop and decoded video.
"""
from dataclasses import dataclass, field, asdict
import math
import numpy as np


IDENTITY = np.array([1., 0., 0., 0.])


def normalize(q):
    q = np.asarray(q, dtype=float)
    n = np.linalg.norm(q)
    if q.shape != (4,) or not np.isfinite(q).all() or n < 1e-8:
        raise ValueError("Invalid orientation quaternion")
    return q / n


def conjugate(q):
    return np.asarray(q) * np.array([1, -1, -1, -1])


def multiply(a, b):
    w, x, y, z = a
    v, i, j, k = b
    return np.array([w*v-x*i-y*j-z*k, w*i+x*v+y*k-z*j,
                     w*j-x*k+y*v+z*i, w*k+x*j-y*i+z*v])


def axis_angle(axis, radians):
    axis = np.asarray(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    return np.r_[math.cos(radians/2), axis * math.sin(radians/2)]


def matrix(q):
    w, x, y, z = normalize(q)
    return np.array([[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
                     [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
                     [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]], dtype=np.float32)


def nwu_to_gl(q):
    """NWU forward/left/up -> GL -Z/-X/+Y (proper basis rotation)."""
    w, x, y, z = normalize(q)
    return np.array([w, -y, z, -x])


def viture_euler_to_gl(roll, pitch, yaw):
    """Gen1/Gen2 pose angles -> camera quaternion, matching the SDK reference demo.

    Positive SDK yaw turns left, pitch looks down, roll tilts right. The demo
    builds forward/up from these angles. Its camera basis equals Ry(yaw) *
    Rx(-pitch) * Rz(-roll). Do not assume the separately reported quaternion
    has the same basis/reference: the Pro 2 packets we measured do not.
    """
    if not all(math.isfinite(value) for value in (roll,pitch,yaw)):
        raise ValueError('Invalid VITURE pose angles')
    r,p,y = math.radians(-roll)/2,math.radians(-pitch)/2,math.radians(yaw)/2
    cr,sr,cp,sp,cy,sy = math.cos(r),math.sin(r),math.cos(p),math.sin(p),math.cos(y),math.sin(y)
    return np.array([cy*cp*cr+sy*sp*sr,cy*sp*cr+sy*cp*sr,
                     sy*cp*cr-cy*sp*sr,cy*cp*sr-sy*sp*cr])


def slerp(a, b, weight):
    a, b = normalize(a), normalize(b)
    dot = float(np.dot(a, b))
    if dot < 0:
        b, dot = -b, -dot
    t = float(np.clip(weight, 0, 1))
    if dot > .9995:
        return normalize(a + t * (b-a))
    angle = math.acos(np.clip(dot, -1, 1))
    return (math.sin((1-t)*angle)*a + math.sin(t*angle)*b) / math.sin(angle)


def view_ray(x, y, width, height, fov_y, rotation):
    scale = math.tan(math.radians(fov_y)/2)
    ray = np.array([(2*x/width-1)*width/height*scale, (1-2*y/height)*scale, -1.])
    ray = rotation @ ray
    return ray / np.linalg.norm(ray)


@dataclass(frozen=True)
class PanelPlacement:
    """A monitor's fixed pose relative to the recentered viewer, in degrees/metres."""
    azimuth: float = 0.
    elevation: float = 0.
    distance: float = 2.5
    scale: float = 1.
    turn: float = 0.
    tilt: float = 0.
    roll: float = 0.

    def __post_init__(self):
        limits = {'azimuth':(-180,180), 'elevation':(-80,80), 'distance':(.5,10),
                  'scale':(.25,3), 'turn':(-75,75), 'tilt':(-75,75), 'roll':(-180,180)}
        for name,(lo,hi) in limits.items():
            value = getattr(self,name)
            if not isinstance(value,(int,float)) or not math.isfinite(value) or not lo <= value <= hi:
                raise ValueError(f'Invalid monitor {name}')

    @property
    def center(self):
        a,e = math.radians(self.azimuth), math.radians(self.elevation)
        return np.array([math.sin(a)*math.cos(e), math.sin(e), -math.cos(a)*math.cos(e)])*self.distance


@dataclass
class Layout:
    count: int = 3
    width: int = 1920
    height: int = 1080
    distance: float = 2.5
    screen_degrees: float = 44.
    gap_degrees: float = 3.
    placements: dict = field(default_factory=dict)
    # Runtime tracking reference, deliberately excluded from saved placements.
    world_up: tuple[float, float, float] = field(default=(0.,1.,0.),init=False,repr=False)
    _render_key: tuple | None = field(default=None,init=False,repr=False)
    _render_arrays: tuple | None = field(default=None,init=False,repr=False)
    _panel_frames: tuple | None = field(default=None,init=False,repr=False)

    def __post_init__(self):
        if not 1 <= self.count <= 5 or not 320 <= self.width <= 3840 or not 180 <= self.height <= 2160:
            raise ValueError("Use 1–5 screens, each 320–3840 × 180–2160 pixels")
        if self.width*self.count > 16384:
            raise ValueError("Desktop texture cannot exceed 16384 pixels")

    @property
    def half_size(self):
        w = self.distance * math.tan(math.radians(self.screen_degrees)/2)
        return np.array([w, w*self.height/self.width])

    def panel(self, index):
        center,right,up,normal,size = self.panel_frame(index)
        return center, right, normal

    def placement(self,index):
        if not 0 <= index < self.count:
            raise IndexError('Invalid display')
        if index in self.placements:
            return self.placements[index]
        return PanelPlacement(azimuth=(index-(self.count-1)/2)*(self.screen_degrees+self.gap_degrees),
                              distance=self.distance)

    def update_panel(self,index,**changes):
        values = asdict(self.placement(index))
        values.update(changes)
        self.placements[index] = PanelPlacement(**values)

    def panel_frame(self,index):
        placement = self.placement(index)
        center = placement.center
        # A zero-tilt monitor stands vertically. Turn it toward the viewer only
        # around gravity; aiming its normal at the eye in 3D also pitches it.
        # That hidden pitch made adjacent monitors lean in opposite directions
        # when viewed between their centers, even with every angle set to zero.
        up = np.asarray(self.world_up,dtype=float)
        up /= np.linalg.norm(up)
        normal = -center/placement.distance
        normal -= up*np.dot(normal,up)
        if np.linalg.norm(normal) < 1e-6:
            # Directly above/below the viewer there is no unique heading. The
            # upright screen is edge-on, but still needs a finite stable basis.
            axis = np.eye(3)[np.argmin(np.abs(up))]
            normal = axis-up*np.dot(axis,up)
        normal /= np.linalg.norm(normal)
        right = np.cross(up,normal)
        local = multiply(axis_angle([0,1,0],math.radians(placement.turn)),
                 multiply(axis_angle([1,0,0],math.radians(placement.tilt)),
                          axis_angle([0,0,1],math.radians(placement.roll))))
        basis = np.column_stack([right,up,normal]) @ matrix(local)
        return center,basis[:,0],basis[:,1],basis[:,2],self.half_size*placement.scale

    def cached_frames(self):
        """Share unchanged geometry between drawing and high-rate pointer events."""
        key = (self.count,self.width,self.height,self.distance,self.screen_degrees,self.gap_degrees,
               tuple(self.world_up),tuple(self.placements.get(i) for i in range(self.count)))
        if key != self._render_key:
            self._panel_frames = tuple(self.panel_frame(i) for i in range(self.count))
            for frame in self._panel_frames:
                for array in frame:
                    array.flags.writeable = False
            self._render_arrays = None
            self._render_key = key
        return self._panel_frames

    def render_arrays(self):
        frames = self.cached_frames()
        if self._render_arrays is None:
            self._render_arrays = tuple(np.ascontiguousarray([frame[column] for frame in frames],dtype=np.float32)
                                        for column in range(5))
            for array in self._render_arrays:
                array.flags.writeable = False
        return self._render_arrays

    def place_on_ray(self,index,ray):
        ray = np.asarray(ray,dtype=float)
        ray /= np.linalg.norm(ray)
        self.update_panel(index,azimuth=math.degrees(math.atan2(ray[0],-ray[2])),
                          elevation=float(np.clip(math.degrees(math.asin(np.clip(ray[1],-1,1))),-80,80)))

    def preset(self,name):
        if name not in ('arc','flat','stack'):
            raise ValueError('Unknown layout preset')
        placements = {}
        for i in range(self.count):
            offset = i-(self.count-1)/2
            if name == 'flat':
                x = offset*(self.half_size[0]*2 + .12)
                a = math.degrees(math.atan2(x,self.distance))
                placements[i] = PanelPlacement(azimuth=a,distance=math.hypot(x,self.distance),turn=a)
            elif name == 'stack':
                elevation = offset*(math.degrees(2*math.atan(self.half_size[1]/self.distance))+3)
                placements[i] = PanelPlacement(elevation=float(np.clip(elevation,-80,80)),distance=self.distance)
        self.placements = placements

    def to_dict(self):
        return {'version':1,'count':self.count,'width':self.width,'height':self.height,
                'panels':[asdict(self.placement(i)) for i in range(self.count)]}

    def restore(self,data):
        if not isinstance(data,dict) or data.get('version') != 1 or (
            data.get('count'),data.get('width'),data.get('height')) != (self.count,self.width,self.height):
            raise ValueError('Saved layout does not match the display configuration')
        panels = data.get('panels')
        if not isinstance(panels,list) or len(panels) != self.count or not all(isinstance(p,dict) for p in panels):
            raise ValueError('Invalid saved monitor list')
        # Validate the entire layout before modifying anything.
        restored = {i:PanelPlacement(**p) for i,p in enumerate(panels)}
        self.placements = restored

    def hit(self, ray, origin=None):
        ray = np.asarray(ray, dtype=float)
        origin = np.zeros(3) if origin is None else np.asarray(origin)
        best = None
        for index,(center,right,up,normal,(hw,hh)) in enumerate(self.cached_frames()):
            denom = np.dot(ray, normal)
            if denom >= -1e-6:
                continue
            t = np.dot(center-origin, normal) / denom
            p = origin+t*ray-center
            u, v = np.dot(p, right)/(2*hw)+.5, .5-np.dot(p,up)/(2*hh)
            if t > 0 and 0 <= u < 1 and 0 <= v < 1 and (best is None or t < best[0]):
                best = (t, index*self.width+int(u*self.width), int(v*self.height))
        return None if best is None else best[1:]


def video_uv(ray, projection="360", packing="mono", eye=0):
    ray = np.asarray(ray)/np.linalg.norm(ray)
    longitude = math.atan2(ray[0], -ray[2])
    if projection == "180" and abs(longitude) > math.pi/2:
        return None
    u = .5 + longitude / (math.pi if projection == "180" else 2*math.pi)
    v = .5 - math.asin(np.clip(ray[1], -1, 1))/math.pi
    if packing == "sbs":
        u = (u+eye)/2
    elif packing == "tb":
        v = (v+eye)/2
    return u, v
