import http.client
import json
import math
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit

import numpy as np
import pytest

from spacewalker.browser_video import BrowserVideo,spherical_angles
from spacewalker.geometry import axis_angle,matrix,multiply,viture_euler_to_gl
from spacewalker.tracking import PoseState


@pytest.mark.skipif(not shutil.which('node'),reason='Browser camera tests require Node.js')
def test_browser_camera_zoom_is_independent_of_tracking():
    subprocess.run(['node','--test',str(Path(__file__).with_name('browser_view.mjs'))],check=True,
                   capture_output=True,text=True)


@pytest.mark.parametrize('angles',[(0,0,0),(0,0,45),(0,-30,0),(25,0,0),(-20,34,179),(15,-80,-179),(0,-90,25),(0,90,-45)])
def test_youtube_angles_preserve_camera_orientation(angles):
    q=viture_euler_to_gl(*angles)
    pose=spherical_angles(q)
    restored=multiply(axis_angle([0,1,0],math.radians(pose['yaw'])),
              multiply(axis_angle([1,0,0],math.radians(pose['pitch'])),
                       axis_angle([0,0,1],math.radians(pose['roll']))))
    np.testing.assert_allclose(matrix(restored),matrix(q),atol=1e-6)
    assert 0<=pose['yaw']<360 and -90<=pose['pitch']<=90
    assert pose['pitch']==pytest.approx(-angles[1],abs=1e-5)


def test_browser_snapshot_does_not_advance_native_smoothing():
    pose=PoseState();pose.push(viture_euler_to_gl(0,20,10))
    pose.push(viture_euler_to_gl(15,30,90))
    pose.orientation(100)
    filtered=pose.filtered.copy();last_render=pose.last_render
    q,age=pose.snapshot()
    assert age<.5
    np.testing.assert_allclose(q,multiply(pose.center,pose.raw))
    np.testing.assert_array_equal(pose.filtered,filtered)
    assert pose.last_render==last_render
    pose.recenter()
    np.testing.assert_allclose(pose.snapshot()[0],[1,0,0,0],atol=1e-6)


@pytest.fixture
def bridge():
    b=BrowserVideo()
    try:yield b
    finally:b.close()


def request(b,path,method='GET',headers=None):
    c=http.client.HTTPConnection('127.0.0.1',b.http.server_port,timeout=2)
    c.request(method,path,headers=headers or {})
    response=c.getresponse();status=response.status;data=response.read();c.close()
    return status,data


def test_local_player_restricts_assets_origin_and_commands(bridge):
    assert urlsplit(bridge.url('https://example.org/video?a=b')).query==''
    assert bridge.token in urlsplit(bridge.url()).fragment
    assert request(bridge,'/')[0]==200
    assert request(bridge,'/view.js')[0]==200
    assert request(bridge,'/../tracking.py')[0]==404
    assert request(bridge,'/events')[0]==403
    assert request(bridge,'/events?token=%E2%98%83')[0]==403
    assert request(bridge,'/events?token='+bridge.token,headers={'Origin':'https://example.org'})[0]==403
    assert request(bridge,'/',headers={'Host':'evil.example'})[0]==403
    assert request(bridge,'/action/recenter','POST')[0]==403
    assert request(bridge,'/action/recenter?token='+bridge.token,'POST',{'Origin':bridge.origin})[0]==204
    assert bridge.commands.get_nowait()=='recenter'
    assert request(bridge,'/action/shell?token='+bridge.token,'POST')[0]==404
    for _ in range(16):request(bridge,'/action/recenter?token='+bridge.token,'POST')
    assert request(bridge,'/action/recenter?token='+bridge.token,'POST')[0]==429


def test_pose_stream_delivers_latest_sample_and_shuts_down(bridge):
    c=http.client.HTTPConnection('127.0.0.1',bridge.http.server_port,timeout=2)
    c.request('GET','/events?token='+bridge.token,headers={'Origin':bridge.origin})
    response=c.getresponse()
    assert response.status==200 and response.getheader('Content-Type')=='text/event-stream'
    line=response.readline();response.readline()
    assert json.loads(line.removeprefix(b'data: '))['tracking'] is False
    bridge.publish(viture_euler_to_gl(0,-20,45),.003,26)
    packet=json.loads(response.readline().removeprefix(b'data: '));response.readline()
    assert packet['tracking'] and packet['age_ms']==3
    assert packet['yaw']==pytest.approx(45) and packet['pitch']==pytest.approx(20)
    assert packet['fov_y']==26
    bridge.close()
    assert response.read()==b''
    c.close()


def test_command_routes_are_exact_and_rejected_connections_close(bridge):
    assert request(bridge,'/recenter?token='+bridge.token,'POST')[0] == 404
    connection = http.client.HTTPConnection('127.0.0.1', bridge.http.server_port, timeout=2)
    try:
        connection.request('POST', '/action/recenter?token=wrong', body=b'unread body')
        response = connection.getresponse()
        assert response.status == 403
        assert response.getheader('Connection') == 'close'
        response.read()
    finally:
        connection.close()
