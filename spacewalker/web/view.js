// YouTube's public camera API uses field of view along the longer viewport edge.
// Zoom changes are independent of whether a fresh head pose is available.
export class YouTubeCamera {
  constructor(){this.fov=null;this.sequence=null;}
  update(verticalFov,width,height,pose=null){
    const aspect=width/Math.max(1,height);
    const longer=2*Math.atan(Math.tan(verticalFov*Math.PI/360)*Math.max(1,aspect))*180/Math.PI;
    const fov=Math.max(30,Math.min(120,longer));
    const props={};
    if(this.fov===null||Math.abs(fov-this.fov)>1e-4){props.fov=fov;this.fov=fov;}
    if(pose&&pose.sequence!==this.sequence){
      Object.assign(props,{yaw:pose.yaw,pitch:pose.pitch,roll:pose.roll});
      this.sequence=pose.sequence;
    }
    return Object.keys(props).length?{...props,enableOrientationSensor:false}:null;
  }
}
