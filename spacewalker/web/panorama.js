// Direct equirectangular video is sampled once by the browser's GPU.
export class Panorama {
  constructor(canvas) {
    this.canvas=canvas;
    this.gl=canvas.getContext('webgl',{alpha:false,antialias:false,depth:false});
    if(!this.gl) throw new Error('WebGL is unavailable. Enable hardware acceleration in Helium.');
    const gl=this.gl;
    const compile=(type,source)=>{const s=gl.createShader(type);gl.shaderSource(s,source);gl.compileShader(s);
      if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(s));return s;};
    const vs=compile(gl.VERTEX_SHADER,'attribute vec2 position; void main(){gl_Position=vec4(position,0.,1.);}');
    const fs=compile(gl.FRAGMENT_SHADER,`precision highp float;
      uniform sampler2D video; uniform vec2 resolution,texSize; uniform mat3 orientation;
      uniform float fov; uniform int projection,packing; uniform bool stereo;
      const float PI=3.141592653589793;
      void main(){
        float ew=resolution.x/(stereo?2.:1.);
        float eye=stereo&&gl_FragCoord.x>=ew?1.:0.;
        vec2 ndc=vec2((gl_FragCoord.x-eye*ew)/ew,gl_FragCoord.y/resolution.y)*2.-1.;
        vec3 ray=normalize(orientation*vec3(ndc.x*ew/resolution.y*tan(fov*.5),ndc.y*tan(fov*.5),-1.));
        float lon=atan(ray.x,-ray.z),lat=asin(clamp(ray.y,-1.,1.));
        if(projection==180&&abs(lon)>PI*.5){gl_FragColor=vec4(0,0,0,1);return;}
        vec2 uv=vec2(.5+lon/(projection==180?PI:2.*PI),.5-lat/PI),lo=vec2(0),hi=vec2(1);
        if(packing==1){uv.x=(uv.x+eye)*.5;lo.x=eye*.5;hi.x=lo.x+.5;}
        if(packing==2){uv.y=(uv.y+eye)*.5;lo.y=eye*.5;hi.y=lo.y+.5;}
        gl_FragColor=texture2D(video,clamp(uv,lo+.5/texSize,hi-.5/texSize));
      }`);
    this.program=gl.createProgram();gl.attachShader(this.program,vs);gl.attachShader(this.program,fs);gl.linkProgram(this.program);
    if(!gl.getProgramParameter(this.program,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(this.program));
    gl.deleteShader(vs);gl.deleteShader(fs);
    this.buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,this.buffer);
    gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),gl.STATIC_DRAW);
    this.texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,this.texture);
    for(const axis of [gl.TEXTURE_WRAP_S,gl.TEXTURE_WRAP_T])gl.texParameteri(gl.TEXTURE_2D,axis,gl.CLAMP_TO_EDGE);
    for(const filter of [gl.TEXTURE_MIN_FILTER,gl.TEXTURE_MAG_FILTER])gl.texParameteri(gl.TEXTURE_2D,filter,gl.LINEAR);
    this.uniforms={};for(const name of ['video','resolution','texSize','orientation','fov','projection','packing','stereo'])
      this.uniforms[name]=gl.getUniformLocation(this.program,name);
    this.frameDirty=true;this.lastTime=-1;
  }
  setVideo(video){
    this.video=video;this.frameDirty=true;this.lastTime=-1;
    const mark=()=>{if(this.video!==video)return;this.frameDirty=true;video.requestVideoFrameCallback(mark);};
    if(video.requestVideoFrameCallback)video.requestVideoFrameCallback(mark);
  }
  draw(q,fov,projection,packing,stereo){
    const gl=this.gl,v=this.video;if(!v||v.readyState<2)return;
    const width=Math.max(1,Math.round(this.canvas.clientWidth*devicePixelRatio));
    const height=Math.max(1,Math.round(this.canvas.clientHeight*devicePixelRatio));
    if(this.canvas.width!==width||this.canvas.height!==height){this.canvas.width=width;this.canvas.height=height;}
    gl.viewport(0,0,width,height);gl.useProgram(this.program);gl.bindTexture(gl.TEXTURE_2D,this.texture);
    if(this.frameDirty||(!v.requestVideoFrameCallback&&v.currentTime!==this.lastTime)){
      gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,false);
      gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,v);
      this.frameDirty=false;this.lastTime=v.currentTime;
    }
    gl.bindBuffer(gl.ARRAY_BUFFER,this.buffer);const attr=gl.getAttribLocation(this.program,'position');
    gl.enableVertexAttribArray(attr);gl.vertexAttribPointer(attr,2,gl.FLOAT,false,0,0);
    const [w,x,y,z]=q;
    // Column-major form of the same camera matrix used by the native viewer.
    const m=new Float32Array([1-2*(y*y+z*z),2*(x*y+z*w),2*(x*z-y*w),
      2*(x*y-z*w),1-2*(x*x+z*z),2*(y*z+x*w),2*(x*z+y*w),2*(y*z-x*w),1-2*(x*x+y*y)]);
    gl.uniformMatrix3fv(this.uniforms.orientation,false,m);gl.uniform1i(this.uniforms.video,0);
    gl.uniform2f(this.uniforms.resolution,width,height);gl.uniform2f(this.uniforms.texSize,v.videoWidth,v.videoHeight);
    gl.uniform1f(this.uniforms.fov,fov*Math.PI/180);gl.uniform1i(this.uniforms.projection,Number(projection));
    gl.uniform1i(this.uniforms.packing,{mono:0,sbs:1,tb:2}[packing]);gl.uniform1i(this.uniforms.stereo,stereo?1:0);
    gl.drawArrays(gl.TRIANGLES,0,3);
  }
}
