import {Panorama} from './panorama.js';
import {YouTubeCamera} from './view.js';
const $=id=>document.getElementById(id);
const params=new URLSearchParams(location.hash.slice(1));
const token=params.get('token')||'';
document.title=params.get('title')||'Spacewalker 360';
let pose=null,received=0,player=null,kind=null,media=null,panorama=null,generation=0;
let tracking=true,fov=90,calibratedFov=26,viewPreset='wide',sourceError=false,lastProbe=0,spherical=false;
let camera=new YouTubeCamera(),qualityLabel='';
let frozen=[1,0,0,0],statusText='',youtubePromise=null;
const message=(text,error=false)=>{$('message').textContent=text;$('message').dataset.error=String(error);};
async function action(name){
  const response=await fetch('/action/'+name+'?token='+encodeURIComponent(token),{method:'POST'});
  if(!response.ok)throw new Error('The app connection ended. Reopen Browser 360 from Spacewalker.');
}
function report(error){message(error.message||String(error),true);}
function youtubeId(value){
  const u=new URL(value),host=u.hostname.toLowerCase();
  let id;
  if(host==='youtu.be')id=u.pathname.split('/')[1];
  else if(['youtube.com','www.youtube.com','m.youtube.com','youtube-nocookie.com','www.youtube-nocookie.com'].includes(host)){
    const parts=u.pathname.split('/');
    id=parts[1]==='watch'?u.searchParams.get('v'):['embed','shorts','live'].includes(parts[1])?parts[2]:null;
  }
  return id&&/^[\w-]{11}$/.test(id)?id:null;
}
function loadYouTubeAPI(){
  if(window.YT?.Player)return Promise.resolve();
  if(!youtubePromise)youtubePromise=new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>reject(new Error('YouTube did not load. Allow YouTube scripts/embeds for this local player in Helium and try again.')),15000);
    window.onYouTubeIframeAPIReady=()=>{clearTimeout(timer);resolve();};
    const s=document.createElement('script');s.src='https://www.youtube.com/iframe_api';
    s.onerror=()=>{clearTimeout(timer);reject(new Error('YouTube could not be reached. Check the connection and browser blocking settings.'));};
    document.head.appendChild(s);
  }).catch(e=>{youtubePromise=null;throw e;});
  return youtubePromise;
}
function reset(){
  generation++;sourceError=false;spherical=false;camera=new YouTubeCamera();lastProbe=0;qualityLabel='';
  $('clarity').hidden=true;
  if(player){player.destroy();player=null;}
  if(media){media.pause();media.removeAttribute('src');media.load();media=null;}
  let youtube=$('youtube');
  if(!youtube){youtube=document.createElement('div');youtube.id='youtube';$('stage').prepend(youtube);}
  youtube.hidden=true;$('panorama').hidden=true;$('media-controls').hidden=true;$('empty').hidden=true;
}
async function openVideo(value){
  const url=new URL(value);
  if(!['https:','http:'].includes(url.protocol)||url.username||url.password)throw new Error('Use an HTTP or HTTPS video link.');
  reset();const current=generation,id=youtubeId(value);
  if(id){
    kind='youtube';message('Loading YouTube. Press Play in the player if playback does not start.');
    await loadYouTubeAPI();if(current!==generation)return;
    $('youtube').hidden=false;
    player=new YT.Player('youtube',{width:'100%',height:'100%',videoId:id,
      playerVars:{enablejsapi:1,origin:location.origin,playsinline:1,rel:0,fs:1},events:{
        onReady:()=>{if(current!==generation)return;player.setSphericalProperties({enableOrientationSensor:false});
          message('Press Play, then Fullscreen and Recenter. The view follows your head inside 360° videos.');},
        onPlaybackQualityChange:e=>{if(current!==generation)return;
          // This is YouTube's reported quality level, not an inspection of its
          // cross-origin decoded video. The API cannot force a higher stream.
          qualityLabel=({small:'240p',medium:'360p',large:'480p',hd720:'720p',hd1080:'1080p',
            hd1440:'1440p',hd2160:'2160p',hd2880:'2880p',hd4320:'4320p',highres:'High resolution'})[e.data]||'';
          updateClarity();},
        onError:e=>{if(current!==generation)return;sourceError=true;
          const reason={100:'This video is unavailable or private.',101:'The owner disabled embedded playback.',
            150:'The owner disabled embedded playback.',153:'YouTube rejected player identification. Allow referrers for this local page in Helium.',
            5:'YouTube could not play this video in the browser.',2:'This YouTube link is invalid.'}[e.data]||'YouTube could not play this video.';
          message(reason+' Try another public, embeddable 360° video.',true);}
      }});
  }else{
    kind='direct';message('Loading panoramic video…');
    if(!panorama)panorama=new Panorama($('panorama'));
    media=document.createElement('video');media.crossOrigin='anonymous';media.playsInline=true;
    media.preload='auto';media.volume=Number($('volume').value);media.src=url.href;
    const v=media;
    v.addEventListener('error',()=>{if(v!==media)return;sourceError=true;message('This link could not be played. Use a direct MP4/WebM video URL whose server allows cross-origin playback; ordinary website pages are not video files.',true);});
    v.addEventListener('loadedmetadata',()=>{if(v!==media)return;$('seek').max=Number.isFinite(v.duration)?v.duration:0;
      qualityLabel=v.videoWidth+' × '+v.videoHeight;updateClarity();
      message('Panoramic video ready. Press Play, then Fullscreen and Recenter.');});
    v.addEventListener('timeupdate',()=>{if(v===media&&!$('seek').matches(':active'))$('seek').value=v.currentTime;});
    v.addEventListener('play',()=>{$('play').textContent='Pause';});v.addEventListener('pause',()=>{$('play').textContent='Play';});
    panorama.setVideo(v);$('panorama').hidden=false;$('media-controls').hidden=false;v.load();
  }
}
function updateClarity(){
  $('clarity').hidden=kind!=='direct'&&!spherical;
  const quality=qualityLabel?(kind==='youtube'?'YouTube quality: ':'Video: ')+qualityLabel+'. ':'';
  $('clarity').textContent=quality+(viewPreset==='natural'
    ?'Glasses scale magnifies a small part of the panorama. Choose Wide for the default video view.'
    :'Increasing the field of view shows more scene with smaller objects. It cannot add detail missing from the video.')
    +(kind==='youtube'?' For more source detail, choose 4320p (8K) in the player’s Settings → Quality, if available.':'');
}
function updateFov(value){fov=Number(value);$('fov').value=fov;$('fov-value').textContent=Math.round(fov)+'°';updateClarity();}
$('view-preset').addEventListener('change',e=>{
  viewPreset=e.target.value;updateFov(viewPreset==='wide'?90:calibratedFov);
});
$('fov').addEventListener('input',e=>{viewPreset='custom';$('view-preset').value='custom';updateFov(e.target.value);});
$('head-tracking').addEventListener('change',e=>{tracking=e.target.checked;});
$('open-form').addEventListener('submit',e=>{e.preventDefault();openVideo($('url').value.trim()).catch(report);});
$('recenter').addEventListener('click',()=>action('recenter').catch(report));
$('glasses').addEventListener('click',()=>action('glasses').catch(report));
$('controls').addEventListener('click',()=>action('controls').catch(report));
$('fullscreen').addEventListener('click',()=>{
  const p=document.fullscreenElement?document.exitFullscreen():$('stage').requestFullscreen();p.catch(report);
});
$('play').addEventListener('click',()=>{if(media){if(media.paused)media.play().catch(report);else media.pause();}});
$('seek').addEventListener('input',e=>{if(media&&Number.isFinite(media.duration))media.currentTime=Number(e.target.value);});
$('volume').addEventListener('input',e=>{if(media)media.volume=Number(e.target.value);});
let hideTimer;
function showControls(){
  $('stage').classList.add('show-controls');$('stage').classList.remove('hide-pointer');clearTimeout(hideTimer);
  hideTimer=setTimeout(()=>{$('stage').classList.remove('show-controls');$('stage').classList.add('hide-pointer');},2500);
}
$('stage').addEventListener('mousemove',showControls);$('stage').addEventListener('pointerdown',showControls);
$('stage').addEventListener('mouseenter',showControls);
document.addEventListener('fullscreenchange',showControls);
document.addEventListener('keydown',e=>{
  if(e.target.matches('input,select'))return;
  if(e.key.toLowerCase()==='r'){e.preventDefault();action('recenter').catch(report);}
});
if(token){
  const events=new EventSource('/events?token='+encodeURIComponent(token));
  events.onmessage=e=>{try{pose=JSON.parse(e.data);received=performance.now();
    calibratedFov=pose.fov_y;
    if(viewPreset==='natural'&&fov!==calibratedFov)updateFov(calibratedFov);
  }catch{message('Invalid tracking data. Reopen the browser player.',true);}};
  events.onerror=()=>{received=0;player?.pauseVideo?.();media?.pause();};
  window.addEventListener('pagehide',()=>events.close(),{once:true});
}else message('Open Browser 360 from the Spacewalker app to connect tracking.',true);
function frame(now){
  const fresh=pose?.tracking&&received>0&&now-received<500;
  const status=!token?'Not connected':!received?'App disconnected':!fresh?'Tracking unavailable':tracking?(pose.simulated?'Mouse preview tracking':'Head tracking on'):'Head tracking paused';
  if(status!==statusText){$('tracking').textContent=status;$('tracking').dataset.active=String(fresh&&tracking);statusText=status;}
  if(fresh&&tracking)frozen=pose.quaternion;
  if(kind==='youtube'&&player?.getPlayerState&&!sourceError){
    if(now-lastProbe>500){
      const props=player.getSphericalProperties?.()||{};spherical=Number.isFinite(props.yaw);lastProbe=now;updateClarity();
      if(player.getPlayerState()===1){
        if(pose?.stereo)message('YouTube needs normal 2D glasses mode. Restore the glasses display mode in Spacewalker → Settings → View.',true);
        else if(!spherical)message('Waiting for a 360° video. Ordinary videos and ads do not support looking around.');
        else message('360° video connected. Move to glasses, enter Fullscreen, and Recenter.');
      }
    }
    if(spherical&&!pose?.stereo){
      const rect=player.getIframe().getBoundingClientRect();
      const props=camera.update(fov,rect.width,rect.height,fresh&&tracking?pose:null);
      if(props)player.setSphericalProperties(props);
    }
  }else if(kind==='direct'&&panorama&&!sourceError){
    try{panorama.draw(frozen,fov,$('projection').value,$('packing').value,Boolean(pose?.stereo));}
    catch(e){sourceError=true;message('The browser could not sample this video. Check WebGL and the video server’s cross-origin permissions. '+e.message,true);}
  }
  requestAnimationFrame(frame);
}
requestAnimationFrame(frame);showControls();
const initial=params.get('video');if(initial){$('url').value=initial;openVideo(initial).catch(report);}
