import assert from 'node:assert/strict';
import {test} from 'node:test';
import {YouTubeCamera} from '../spacewalker/web/view.js';

test('zoom and viewport changes work without a tracking connection',()=>{
  const camera=new YouTubeCamera();
  const initial=camera.update(26,1920,1080);
  assert.ok(initial.fov>44&&initial.fov<45);
  assert.equal(initial.enableOrientationSensor,false);
  assert.equal(camera.update(26,1920,1080),null);
  const wide=camera.update(60,1920,1080);
  assert.ok(wide.fov>91&&wide.fov<92);
  assert.equal(wide.yaw,undefined);
  assert.ok(Math.abs(camera.update(60,1080,1920).fov-60)<1e-6);
});

test('pausing tracking leaves camera angles alone while zoom stays live',()=>{
  const camera=new YouTubeCamera();
  const pose={sequence:1,yaw:320,pitch:25,roll:-8};
  assert.equal(camera.update(26,1920,1080,pose).yaw,320);
  assert.equal(camera.update(26,1920,1080,null),null);
  assert.deepEqual(Object.keys(camera.update(60,1920,1080,null)).sort(),['enableOrientationSensor','fov']);
  const resumed=camera.update(60,1920,1080,{...pose,sequence:2,yaw:330});
  assert.equal(resumed.yaw,330);
  assert.equal(resumed.pitch,25);
  assert.equal(resumed.roll,-8);
  assert.equal(resumed.fov,undefined); // Do not repeatedly reset the zoom on head movement.
});

test('YouTube camera obeys API zoom limits and initializes a new player',()=>{
  const camera=new YouTubeCamera();
  assert.equal(camera.update(15,100,100).fov,30);
  assert.equal(camera.update(90,300,100).fov,120);
  const pose={sequence:1,yaw:0,pitch:0,roll:0};
  const other=new YouTubeCamera().update(26,1920,1080,pose);
  assert.ok(other.fov>44);
  assert.equal(other.yaw,0);
});
