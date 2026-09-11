#version 330 core
out vec4 color;
uniform sampler2D source;
uniform vec2 resolution;
uniform vec2 textureSizePx;
uniform mat3 orientation;
uniform float fovY;
uniform bool stereo;
uniform float ipd;
uniform int scene; // 0 desktop, 1 flat video, 2 VR180, 3 VR360
uniform int packing; // 0 mono, 1 SBS, 2 top/bottom
uniform bool swapEyes;
uniform int screenCount;
uniform vec2 panelHalfSize;
uniform float distanceM;
uniform vec3 panelCenters[5];
uniform vec3 panelRights[5];
uniform vec3 panelUps[5];
uniform vec3 panelNormals[5];
uniform vec2 panelSizes[5];
uniform bool arranging;
uniform int selectedPanel;
uniform vec2 cursor;
uniform bool hasSource;
uniform bool sharpText;
const float PI = 3.141592653589793;

vec3 desktop(vec2 uv, vec2 lo, vec2 hi) {
    // Catmull-Rom reconstruction keeps text edges clearer than bilinear sampling
    // at fractional head poses. Combine the two positive central weights into
    // one hardware bilinear fetch per axis (9 taps instead of 16).
    vec2 dx = dFdx(uv)*textureSizePx, dy = dFdy(uv)*textureSizePx;
    if (!sharpText || max(length(dx),length(dy))>1.25)
        return texture(source,clamp(uv,lo,hi)).rgb;
    vec2 p=uv*textureSizePx-.5, base=floor(p), f=p-base;
    vec2 f2=f*f, f3=f2*f;
    vec2 w0=-.5*f+f2-.5*f3;
    vec2 w1=1.-2.5*f2+1.5*f3;
    vec2 w2=.5*f+2.*f2-1.5*f3;
    vec2 w3=-.5*f2+.5*f3;
    vec2 middle=w1+w2;
    vec3 xs=vec3(base.x-.5,base.x+.5+w2.x/middle.x,base.x+2.5)/textureSizePx.x;
    vec3 ys=vec3(base.y-.5,base.y+.5+w2.y/middle.y,base.y+2.5)/textureSizePx.y;
    vec3 wx=vec3(w0.x,middle.x,w3.x), wy=vec3(w0.y,middle.y,w3.y);
    vec3 value=vec3(0);
    for (int y=0;y<3;y++) for (int x=0;x<3;x++)
        value+=wx[x]*wy[y]*textureLod(source,clamp(vec2(xs[x],ys[y]),lo,hi),0.).rgb;
    return clamp(value,0.,1.);
}

vec3 video(vec2 st, int eye) {
    vec2 lo = vec2(0), hi = vec2(1);
    if (packing == 1) { st.x = (st.x + float(eye)) * .5; lo.x = float(eye)*.5; hi.x = lo.x+.5; }
    if (packing == 2) { st.y = (st.y + float(eye)) * .5; lo.y = float(eye)*.5; hi.y = lo.y+.5; }
    vec2 inset = .5 / textureSizePx;
    return texture(source, clamp(st, lo+inset, hi-inset)).rgb;
}

void main() {
    float eyeWidth = resolution.x / (stereo ? 2.0 : 1.0);
    int physicalEye = stereo && gl_FragCoord.x >= eyeWidth ? 1 : 0;
    int mediaEye = swapEyes ? 1-physicalEye : physicalEye;
    vec2 local = vec2(gl_FragCoord.x-float(physicalEye)*eyeWidth, gl_FragCoord.y);
    vec2 ndc = local / vec2(eyeWidth, resolution.y)*2.0-1.0;
    float scale = tan(radians(fovY)*.5);
    vec3 ray = normalize(orientation * vec3(ndc.x*eyeWidth/resolution.y*scale, ndc.y*scale, -1));
    vec3 origin = stereo ? orientation*vec3((float(physicalEye)-.5)*ipd, 0, 0) : vec3(0);
    float lon = atan(ray.x, -ray.z);
    float lat = asin(clamp(ray.y, -1, 1));
    if (scene >= 2) {
        if (!hasSource || (scene == 2 && abs(lon) > PI*.5)) { color=vec4(0,0,0,1); return; }
        vec2 st = vec2(.5+lon/(scene==2 ? PI : 2.*PI), .5-lat/PI);
        color = vec4(video(st,mediaEye),1); return;
    }
    int count = scene == 1 ? 1 : screenCount;
    float nearest = 1e20;
    // Optical see-through: emit no display light outside an actual screen.
    // Alpha transparency would reveal the host desktop, not the world beyond the lenses.
    vec3 result = vec3(0);
    for (int i=0; i<5; ++i) {
        if (i>=count) break;
        vec3 center = scene == 1 ? vec3(0,0,-distanceM) : panelCenters[i];
        vec3 right = scene == 1 ? vec3(1,0,0) : panelRights[i];
        vec3 up = scene == 1 ? vec3(0,1,0) : panelUps[i];
        vec3 normal = scene == 1 ? vec3(0,0,1) : panelNormals[i];
        vec2 size = scene == 1 ? panelHalfSize : panelSizes[i];
        float denom = dot(ray,normal);
        if (denom >= -.00001) continue;
        float t = dot(center-origin,normal)/denom;
        vec3 p = origin+t*ray-center;
        vec2 st = vec2(dot(p,right),-dot(p,up))/(2.*size)+.5;
        if (t>0 && t<nearest && all(greaterThanEqual(st,vec2(0))) && all(lessThan(st,vec2(1)))) {
            nearest=t;
            if (!hasSource) { result=vec3(0); continue; }
            if (scene == 1) { result=video(st,mediaEye); continue; }
            vec2 tex = vec2((st.x+float(i))/float(count),st.y);
            vec2 inset=.5/textureSizePx;
            vec2 lo=vec2(float(i)/float(count),0)+inset;
            vec2 hi=vec2(float(i+1)/float(count),1)-inset;
            result=desktop(tex,lo,hi);
            if (arranging) {
                vec2 edge=min(st,1.-st)/max(fwidth(st),vec2(.00001));
                if (min(edge.x,edge.y)<(i==selectedPanel ? 2. : 1.))
                    result=vec3(i==selectedPanel ? .85 : .32);
            }
            vec2 delta = tex*textureSizePx-cursor;
            float r=length(delta);
            if (!arranging && cursor.x >= 0 && r<7.) result = r<4. ? vec3(1) : vec3(.1,.15,.17);
        }
    }
    color=vec4(result,1);
}
