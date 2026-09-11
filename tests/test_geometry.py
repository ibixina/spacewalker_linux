import math
import numpy as np
import pytest
from spacewalker.geometry import (Layout, IDENTITY, axis_angle, conjugate, matrix,
    multiply, normalize, nwu_to_gl, slerp, video_uv, view_ray, viture_euler_to_gl)
from spacewalker.tracking import PoseState, devices


def test_nwu_basis_matches_gl_rotations():
    # NWU positive yaw looks left, positive pitch looks down, roll tilts right.
    yaw = nwu_to_gl(axis_angle([0,0,1], math.pi/2))
    np.testing.assert_allclose(matrix(yaw)@[0,0,-1], [-1,0,0], atol=1e-6)
    pitch = nwu_to_gl(axis_angle([0,1,0], math.pi/2))
    np.testing.assert_allclose(matrix(pitch)@[0,0,-1], [0,-1,0], atol=1e-6)


def test_recenter_preserves_world_anchor_after_compound_rotation():
    center = multiply(axis_angle([0,1,0], .4), axis_angle([1,0,0], .2))
    relative = axis_angle([0,1,0], -.6)
    state = PoseState()
    state.push(center)
    np.testing.assert_allclose(matrix(state.orientation()), np.eye(3), atol=1e-6)
    state.push(multiply(center, relative))
    np.testing.assert_allclose(matrix(state.orientation()), matrix(relative), atol=1e-6)
    # A world-fixed panel is visible when rotating the camera toward its fixed location.
    layout = Layout()
    ray = matrix(axis_angle([0,1,0], math.radians(47)))@[0,0,-1]
    x,y = layout.hit(ray)
    assert (x,y) == (960,540)
    state.recenter()
    np.testing.assert_allclose(state.orientation(), IDENTITY, atol=1e-6)


def test_recenter_before_first_sample_uses_first_sample():
    state=PoseState()
    state.recenter()
    state.push(axis_angle([0,1,0], 1.2))
    np.testing.assert_allclose(state.orientation(), IDENTITY, atol=1e-6)


def test_recenter_rejects_stale_samples_and_recovers_on_fresh_data(monkeypatch):
    from types import SimpleNamespace
    now = [10.]
    monkeypatch.setattr('spacewalker.tracking.time',SimpleNamespace(monotonic=lambda:now[0]))
    state = PoseState()
    state.push(viture_euler_to_gl(25,32,47))
    state.push(viture_euler_to_gl(30,40,50))
    before = state.orientation()
    now[0] += .51
    assert state.recenter() is False
    np.testing.assert_allclose(state.orientation(),before)
    state.push(viture_euler_to_gl(30,40,50))
    assert state.recenter() is True
    np.testing.assert_allclose(state.orientation(),IDENTITY,atol=1e-6)
    assert state.reference_up == (0.,1.,0.)


@pytest.mark.parametrize('recenter_angles',[(0,20,35),(0,-30,-140),(12,25,179)])
@pytest.mark.parametrize('elevations',[(0,0,0),(-15,12,-1)])
def test_all_monitors_stay_upright_when_faced_after_pitched_recenter(recenter_angles,elevations):
    reference = viture_euler_to_gl(*recenter_angles)
    state = PoseState()
    state.push(reference)
    layout = Layout()
    layout.world_up = state.reference_up
    for i,elevation in enumerate(elevations):
        layout.update_panel(i,elevation=elevation)
        center,right,up,normal,_ = layout.panel_frame(i)
        # Turn within the calibrated frame to face each fixed monitor.
        forward = center/np.linalg.norm(center)
        yaw = -math.degrees(math.atan2(forward[0],-forward[2]))
        pitch = -math.degrees(math.asin(np.clip(forward[1],-1,1)))
        state.push(multiply(reference,viture_euler_to_gl(0,pitch,yaw)))
        view = matrix(state.orientation()).T
        # The middle row stays level when faced, without pitching the monitor
        # toward the eye. Its vertical edges remain parallel to calibrated up.
        np.testing.assert_allclose(view @ right,[1,0,0],atol=1e-6)
        np.testing.assert_allclose(up,[0,1,0],atol=1e-6)
        np.testing.assert_allclose(layout.hit(matrix(state.orientation()) @ [0,0,-1]),
                                   [i*1920+960,540],atol=1)
        # Panels remain fixed, rather than following the current head's up axis.
        assert state.reference_up == layout.world_up
        state.push(multiply(reference,viture_euler_to_gl(15,pitch,yaw)))
        rolled_right = matrix(state.orientation()).T @ right
        assert math.degrees(math.atan2(rolled_right[1],rolled_right[0])) == pytest.approx(15,abs=1e-5)


def test_recenter_keeps_the_horizon_level_without_changing_saved_placement():
    state = PoseState()
    layout = Layout()
    layout.update_panel(0,azimuth=-32,elevation=10,distance=3.4,roll=7)
    saved = layout.to_dict()
    original = layout.render_arrays()
    assert state.reference_up == (0.,1.,0.)
    state.recenter()  # Waiting for the first pose must keep a valid default.
    state.push(viture_euler_to_gl(0,20,35))
    layout.world_up = state.reference_up
    changed = layout.render_arrays()
    np.testing.assert_array_equal(changed[0],original[0])
    np.testing.assert_array_equal(changed[1],original[1])
    assert layout.render_arrays() is changed
    state.push(viture_euler_to_gl(0,0,90))
    assert state.reference_up == layout.world_up
    state.recenter()
    layout.world_up = state.reference_up
    np.testing.assert_allclose(layout.render_arrays()[1],original[1],atol=1e-6)
    assert layout.to_dict() == saved


@pytest.mark.parametrize('world_up',[(0,0,1),(0,0,-1),(1e-9,0,1)])
def test_monitor_pointing_along_gravity_has_valid_geometry(world_up):
    layout = Layout(1)
    layout.world_up = world_up
    center,right,up,normal,_ = layout.panel_frame(0)
    basis = np.column_stack([right,up,normal])
    np.testing.assert_allclose(basis.T @ basis,np.eye(3),atol=1e-6)
    assert np.linalg.det(basis) == pytest.approx(1)
    np.testing.assert_allclose(up,np.array(world_up)/np.linalg.norm(world_up),atol=1e-6)
    assert layout.hit(center) is None  # An upright screen overhead is edge-on.


@pytest.mark.parametrize('reference_angles',[(0,0,0),(0,20,35),(12,25,179)])
def test_monitor_sides_stay_vertical_while_looking_between_screens(reference_angles):
    reference = viture_euler_to_gl(*reference_angles)
    state = PoseState()
    state.push(reference)
    layout = Layout()
    layout.world_up = state.reference_up
    # Independent placements from the reported arrangement. No manual angles.
    for i,(azimuth,elevation) in enumerate([(-11.15,-15.31),(-11.37,11.69),(34.56,-.72)]):
        layout.update_panel(i,azimuth=azimuth,elevation=elevation)
    fixed = layout.render_arrays()
    for heading_offset in (-30,0,23,47):
        state.push(multiply(reference,viture_euler_to_gl(0,0,heading_offset)))
        view = matrix(state.orientation()).T
        for i in range(3):
            center,right,up,normal,(hw,hh) = layout.panel_frame(i)
            for side in (-1,1):
                bottom = view @ (center+side*hw*right-hh*up)
                top = view @ (center+side*hw*right+hh*up)
                if bottom[2] < -.1 and top[2] < -.1:
                    # A perspective divide must not turn the two sides into
                    # opposing slants with a level head, even off-center.
                    assert bottom[0]/-bottom[2] == pytest.approx(top[0]/-top[2],abs=1e-6,rel=1e-6)
            assert layout.render_arrays() is fixed


def test_all_panel_centers_and_outside():
    for count in range(1,6):
        layout=Layout(count)
        for i in range(count):
            center,_,_=layout.panel(i)
            hit=layout.hit(center/np.linalg.norm(center))
            assert abs(hit[0]-(i*1920+960)) <= 1
            assert hit[1] == 540
        assert layout.hit([0,1,0]) is None
        assert layout.hit([0,0,1]) is None


def test_pointer_unprojection_center_and_top():
    np.testing.assert_allclose(view_ray(500,250,1000,500,26,np.eye(3)),[0,0,-1])
    assert view_ray(500,0,1000,500,26,np.eye(3))[1] > 0


@pytest.mark.parametrize('origin', [[0,0,0],[-.032,0,0],[.032,0,0]])
def test_independent_tilted_monitor_maps_texture_to_pointer(origin):
    layout = Layout()
    untouched = layout.panel_frame(0)
    layout.update_panel(1,azimuth=8,elevation=15,distance=3.2,scale=.8,turn=24,tilt=-18,roll=31)
    for before,after in zip(untouched,layout.panel_frame(0)):
        np.testing.assert_array_equal(before,after)
    center,right,up,normal,(hw,hh) = layout.panel_frame(1)
    np.testing.assert_allclose(np.cross(right,up),normal,atol=1e-6)
    for u,v in [(.5,.5),(.1,.15),(.85,.1),(.9,.8)]:
        point = center+right*(2*u-1)*hw+up*(1-2*v)*hh
        ray = point-np.array(origin)
        hit = layout.hit(ray/np.linalg.norm(ray),origin)
        np.testing.assert_allclose(hit,[1920+u*1920,v*1080],atol=1)


def test_overlapping_monitor_uses_nearest_surface():
    layout = Layout()
    layout.update_panel(0,azimuth=0,distance=1.5)
    assert layout.hit([0,0,-1]) == (960,540)
    layout.update_panel(0,distance=4)
    assert layout.hit([0,0,-1]) == (2880,540)


def test_layout_round_trip_validation_and_presets():
    import copy
    import json
    layout = Layout(5)
    layout.preset('flat')
    for i in range(5):
        center,_,_,normal,_ = layout.panel_frame(i)
        assert center[2] == pytest.approx(-2.5)
        np.testing.assert_allclose(normal,[0,0,1],atol=1e-6)
    layout.update_panel(3,azimuth=120,elevation=22,distance=4,roll=-12)
    saved = json.loads(json.dumps(layout.to_dict()))
    restored = Layout(5)
    restored.restore(saved)
    assert restored.to_dict() == saved
    corrupt = copy.deepcopy(saved)
    corrupt['panels'][-1]['distance'] = float('nan')
    with pytest.raises(ValueError):
        restored.restore(corrupt)
    assert restored.to_dict() == saved
    with pytest.raises(ValueError):
        Layout(3).restore(saved)
    layout.preset('stack')
    assert [layout.placement(i).azimuth for i in range(5)] == [0]*5
    assert layout.placement(0).elevation < 0 < layout.placement(4).elevation
    layout.preset('arc')
    assert layout.placement(2).azimuth == 0
    assert layout.placement(4).azimuth == 94


def test_place_in_current_gaze_preserves_distance_and_size():
    layout = Layout()
    layout.update_panel(0,distance=4,scale=1.5)
    direction = np.array([.4,.25,1.])
    layout.place_on_ray(0,direction)
    np.testing.assert_allclose(layout.placement(0).center/4,direction/np.linalg.norm(direction))
    assert layout.placement(0).scale == 1.5


def test_render_geometry_updates_after_edit_preset_and_global_resize():
    layout = Layout()
    original = layout.render_arrays()
    layout.update_panel(1,azimuth=20,elevation=15,distance=4,scale=.7)
    changed = layout.render_arrays()
    assert not np.array_equal(original[0][1],changed[0][1])
    np.testing.assert_allclose(changed[0][1],layout.placement(1).center)
    layout.preset('flat')
    np.testing.assert_allclose(layout.render_arrays()[0][:,2],[-2.5]*3)
    size = layout.render_arrays()[4].copy()
    layout.screen_degrees = 60
    assert np.all(layout.render_arrays()[4] > size)


@pytest.mark.parametrize('packing,eye,expected',[
    ('mono',0,(.5,.5)),('sbs',0,(.25,.5)),('sbs',1,(.75,.5)),
    ('tb',0,(.5,.25)),('tb',1,(.5,.75))])
def test_video_eye_mapping(packing,eye,expected):
    assert video_uv([0,0,-1],'360',packing,eye)==expected


def test_180_behind_is_black_and_poles_are_correct():
    assert video_uv([0,0,1],'180') is None
    assert video_uv([0,1,0])[1] == 0
    assert video_uv([0,-1,0])[1] == 1
    assert video_uv([1,0,0],'180')[0] == 1


def test_slerp_quaternion_sign_and_bad_packets():
    q = axis_angle([0,1,0], 1.1)
    np.testing.assert_allclose(slerp(q,-q,.5),q)
    for invalid in ([0,0,0,0],[float('nan'),0,0,1],[1,2,3]):
        with pytest.raises(ValueError):
            normalize(invalid)


def test_usb_discovery_deduplicates_and_ignores_other_vendors(tmp_path):
    for index,vid,pid in [('a','35ca','1301'),('b','35CA','1301'),('c','1234','0001')]:
        p=tmp_path/index
        p.mkdir()
        (p/'idVendor').write_text(vid)
        (p/'idProduct').write_text(pid)
    assert devices(tmp_path)==[0x1301]


def test_pointer_geometry_cache_preserves_precision_and_invalidates_after_edits():
    from spacewalker.geometry import Layout, axis_angle, matrix
    layout = Layout(5)
    rays = [np.array([x, y, -1.]) for x in (-3., -.6, 0., .6, 3.) for y in (-.3, 0., .3)]
    for mutate in (
        lambda: None,
        lambda: layout.update_panel(1, elevation=25, tilt=-15),
        lambda: setattr(layout, 'world_up', tuple(matrix(axis_angle([0,0,1], .2))[:,1])),
        lambda: setattr(layout, 'screen_degrees', 52),
        lambda: layout.preset('stack'),
    ):
        mutate()
        frames = layout.cached_frames()
        assert frames is layout.cached_frames()
        for i, frame in enumerate(frames):
            for cached, direct in zip(frame, layout.panel_frame(i)):
                np.testing.assert_array_equal(cached, direct)
        cached_hits = [layout.hit(ray) for ray in rays]
        # Force a cold calculation and compare exact integer pixel coordinates.
        layout._render_key = None
        assert cached_hits == [layout.hit(ray) for ray in rays]
        arrays = layout.render_arrays()
        assert all(not a.flags.writeable for a in arrays)
