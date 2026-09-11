import ctypes as C
import numpy as np
import pytest
from spacewalker.tracking import VitureTracker
from spacewalker.geometry import matrix


class Function:
    def __init__(self, lib, name):
        self.lib,self.name=lib,name

    def __call__(self,*args):
        self.lib.calls.append((self.name,args))
        if self.name==self.lib.fail:
            return -3
        if self.name=='create':
            return 0x1234567812345678
        if self.name=='get_device_type':
            return 1
        if self.name=='is_product_id_valid':
            return 1
        if self.name=='is_product_support_imu_frequency':
            return int(args[2]<=2)
        if self.name=='get_display_mode':
            return self.lib.mode
        if self.name=='set_display_mode':
            self.lib.mode=args[1]
        return 0


class Library:
    def __init__(self,fail=None):
        self.calls=[]
        self.fail=fail
        self.mode=0x34

    def __getattr__(self,name):
        if not name.startswith('xr_device_provider_'):
            raise AttributeError(name)
        fn=Function(self,name.removeprefix('xr_device_provider_'))
        setattr(self,name,fn)
        return fn


def tracker(tmp_path,lib):
    path=tmp_path/'libglasses.so'
    path.touch()
    return VitureTracker(str(path),pid=0x1301,loader=lambda path:lib)


def test_callback_lifetime_frequency_and_cleanup(tmp_path):
    lib=Library()
    t=tracker(tmp_path,lib)
    t.start()
    assert t.handle==0x1234567812345678  # Pointer must not truncate to 32 bits.
    assert ('open_imu',(t.handle,1,2)) in lib.calls
    data=(C.c_float*7)(0,0,0,1,0,0,0)
    t.callback(data,10)
    assert t.pose.samples==1
    t.close()
    assert [name for name,_ in lib.calls][-4:]==['close_imu','stop','shutdown','destroy']
    calls=len(lib.calls)
    t.close()
    assert len(lib.calls)==calls


@pytest.mark.parametrize('failure,cleanup',[
    ('initialize',['destroy']), ('start',['shutdown','destroy']),
    ('open_imu',['stop','shutdown','destroy'])])
def test_partial_initialization_cleanup(tmp_path,failure,cleanup):
    lib=Library(failure)
    t=tracker(tmp_path,lib)
    with pytest.raises(RuntimeError):
        t.start()
    assert [name for name,_ in lib.calls][-len(cleanup):]==cleanup
    assert t.handle is None


def test_stereo_restores_exact_original_mode(tmp_path):
    lib=Library()
    t=tracker(tmp_path,lib)
    t.start()
    t.set_stereo(True)
    t.set_stereo(True)
    assert lib.mode==0x32
    t.close()
    assert lib.mode==0x34


def test_cleanup_continues_after_error(tmp_path):
    lib=Library()
    t=tracker(tmp_path,lib)
    t.start()
    lib.fail='close_imu'
    assert t.close()
    assert lib.calls[-1][0]=='destroy'


def reference_demo_matrix(roll,pitch,yaw):
    """Forward/up construction from the supplied VITURE glasses-demo main.cpp."""
    import math
    az,el,rl = map(math.radians,(-yaw,-pitch,roll))
    forward = np.array([math.sin(az)*math.cos(el),math.sin(el),-math.cos(az)*math.cos(el)])
    right = np.array([-forward[2],0,forward[0]])
    right /= np.linalg.norm(right)
    up = np.cross(right,forward)*math.cos(rl)+right*math.sin(rl)
    return np.column_stack([np.cross(forward,up),up,-forward])


@pytest.mark.parametrize('angles',[(0,0,30),(0,25,0),(20,0,0),(20,12,47),(-15,-35,-125),(8,13,179),(8,13,-179)])
def test_sdk_callback_matches_reference_demo_for_each_axis_and_combined_pose(tmp_path,angles):
    t = tracker(tmp_path,Library())
    # Deliberately unchanged quaternion channels: the Gen1/Gen2 reference path uses angles.
    t.callback((C.c_float*7)(0,0,0,1,0,0,0),0)
    t.callback((C.c_float*7)(*angles,1,0,0,0),1)
    np.testing.assert_allclose(matrix(t.pose.orientation()),reference_demo_matrix(*angles),atol=1e-6)
    t.pose.recenter()
    np.testing.assert_allclose(matrix(t.pose.orientation()),np.eye(3),atol=1e-6)
    next_angles = (angles[0]+7,angles[1]-5,angles[2]+15)
    t.callback((C.c_float*7)(*next_angles,1,0,0,0),2)
    np.testing.assert_allclose(matrix(t.pose.orientation()),
        reference_demo_matrix(*angles).T @ reference_demo_matrix(*next_angles),atol=1e-6)


def test_recorded_pro2_packet_uses_demo_angles_instead_of_wrong_quaternion_basis(tmp_path):
    from spacewalker.geometry import nwu_to_gl
    t = tracker(tmp_path,Library())
    # Captured from the user's Pro 2, 2026-09-10. Its quaternion channels do not
    # describe the same NWU rotation as the first three SDK fields.
    packet = (20.7422580719,12.4026002884,4.6501746178,
              .9778903127,-.1134302914,.0202425011,-.1745119691)
    t.callback((C.c_float*7)(0,0,0,1,0,0,0),0)
    t.callback((C.c_float*7)(*packet),1)
    expected = reference_demo_matrix(*packet[:3])
    np.testing.assert_allclose(matrix(t.pose.orientation()),expected,atol=1e-6)
    assert np.linalg.norm(matrix(nwu_to_gl(packet[3:]))-expected) > .5
    samples = t.pose.samples
    t.callback((C.c_float*7)(float('nan'),0,0,1,0,0,0),2)
    assert t.pose.samples == samples
