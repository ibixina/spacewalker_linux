/* MIT. Persistent Wayland screencopy client; no encoder, frame queue or subprocess per frame. */
#define _GNU_SOURCE
#include <wayland-client.h>
#include "screencopy.h"
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

struct capture_buffer {
    struct wl_buffer *buffer;
    unsigned char *pixels;
    size_t size;
    uint32_t flags;
};
struct output {
    struct wl_output *wl;
    uint32_t id;
    char name[256];
    struct zwlr_screencopy_frame_v1 *frame;
    struct capture_buffer buffers[2];
    uint32_t format, width, height, stride;
    int index, front, back;
    uint64_t generation;
    double captured, next;
};
static struct output outputs[64];
static int noutputs, count, width, height, framefd, failed, dirty;
static size_t framebytes;
static uint64_t sequence;
static unsigned char *shared;
static int writing_slot = -1;
static uint64_t slot_generations[3][5], published_generations[5];
static struct wl_shm *shm;
static struct zwlr_screencopy_manager_v1 *manager;
static volatile sig_atomic_t running = 1;

static void stop(int sig) { (void)sig; running = 0; }
static double now(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec + t.tv_nsec / 1e9;
}
static void fail(const char *s) { fprintf(stderr, "%s\n", s); failed = 1; }
static void geometry(void *d, struct wl_output *o, int32_t x, int32_t y,
    int32_t pw, int32_t ph, int32_t sub, const char *make, const char *model, int32_t tr) {}
static void mode(void *d, struct wl_output *o, uint32_t f, int32_t w, int32_t h, int32_t r) {}
static void done(void *d, struct wl_output *o) {}
static void scale(void *d, struct wl_output *o, int32_t s) {}
static void name(void *d, struct wl_output *o, const char *s) {
    snprintf(((struct output *)d)->name, 256, "%s", s);
}
static void description(void *d, struct wl_output *o, const char *s) {}
static const struct wl_output_listener output_listener = {geometry,mode,done,scale,name,description};
static void global(void *data, struct wl_registry *r, uint32_t id, const char *iface, uint32_t v) {
    if (!strcmp(iface, "wl_shm")) shm = wl_registry_bind(r,id,&wl_shm_interface,1);
    else if (!strcmp(iface,"zwlr_screencopy_manager_v1") && v >= 3)
        manager = wl_registry_bind(r,id,&zwlr_screencopy_manager_v1_interface,3);
    else if (!strcmp(iface,"wl_output") && v >= 4 && noutputs < 64) {
        struct output *o = &outputs[noutputs++];
        o->id = id; o->index = -1; o->front = -1;
        o->wl = wl_registry_bind(r,id,&wl_output_interface,4);
        wl_output_add_listener(o->wl,&output_listener,o);
    }
}
static void removed(void *d, struct wl_registry *r, uint32_t id) {
    for (int i=0;i<noutputs;i++) if (outputs[i].id==id && outputs[i].index>=0)
        fail("A virtual monitor was removed. Restart the monitors to reconnect.");
}
static const struct wl_registry_listener registry_listener = {global,removed};
static void frame_buffer(void *d, struct zwlr_screencopy_frame_v1 *f,
                         uint32_t format, uint32_t w, uint32_t h, uint32_t stride) {
    struct output *o = d;
    if (w != (uint32_t)width || h != (uint32_t)height || stride < w*4 ||
        (format != WL_SHM_FORMAT_XRGB8888 && format != WL_SHM_FORMAT_ARGB8888 &&
         format != WL_SHM_FORMAT_XBGR8888 && format != WL_SHM_FORMAT_ABGR8888)) {
        fail("Virtual monitor mode/format changed. Restart monitors with the desired resolution."); return;
    }
    if (o->generation && (stride!=o->stride || format!=o->format)) {
        fail("Virtual monitor capture format changed. Restart monitors."); return;
    }
    o->width=w; o->height=h; o->stride=stride; o->format=format;
    struct capture_buffer *b=&o->buffers[o->back];
    if (!b->buffer) {
        b->size=(size_t)stride*h;
        int fd=memfd_create("spacewalker-capture",MFD_CLOEXEC);
        if (fd<0 || ftruncate(fd,b->size)<0) { if(fd>=0)close(fd); fail("Cannot allocate capture buffer."); return; }
        b->pixels=mmap(NULL,b->size,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
        if (b->pixels==MAP_FAILED) { close(fd); b->pixels=NULL; fail("Cannot map capture buffer."); return; }
        struct wl_shm_pool *pool=wl_shm_create_pool(shm,fd,b->size);
        b->buffer=wl_shm_pool_create_buffer(pool,0,w,h,stride,format);
        wl_shm_pool_destroy(pool); close(fd);
        if(!o->generation) fprintf(stderr,"Capture %s: %ux%u, format 0x%x, stride %u (changed-screen publishing)\n",o->name,w,h,format,stride);
    }
}
static void swizzle_row(uint32_t *restrict dst, const uint32_t *restrict src, int count) {
    /* Separate SHM/atlas allocations cannot alias. Whole-pixel operations let
       the compiler vectorize this conversion instead of four byte stores/pixel. */
    for(int x=0;x<count;x++) {
        uint32_t p=src[x];
        dst[x]=0xff000000u | (p&0x0000ff00u) | ((p>>16)&0xffu) | ((p&0xffu)<<16);
    }
}
static void frame_flags(void *d, struct zwlr_screencopy_frame_v1 *f, uint32_t flags) {
    struct output *o=d;
    o->buffers[o->back].flags=flags;
}
static void frame_ready(void *d, struct zwlr_screencopy_frame_v1 *f, uint32_t hi, uint32_t lo, uint32_t ns) {
    struct output *o=d;
    /* Some compositors report full damage even for an unchanged output.
       Suppress duplicate pixels too, so an idle monitor costs no atlas copy
       or GPU upload. The front buffer remains stable while back is captured. */
    int changed=o->front<0 || o->buffers[o->front].flags!=o->buffers[o->back].flags ||
        memcmp(o->buffers[o->front].pixels,o->buffers[o->back].pixels,o->buffers[o->back].size);
    o->front=o->back;
    if(changed) { o->generation++; dirty=1; }
    double stamp=(double)(((uint64_t)hi<<32)|lo)+ns/1e9;
    double t=now();
    /* Hyprland reports CLOCK_MONOTONIC. Reject an unrelated clock origin. */
    if(changed) o->captured=stamp>0 && stamp<=t+.01 && t-stamp<60 ? stamp : t;
    zwlr_screencopy_frame_v1_destroy(f); o->frame=NULL;
}
static void copy_output(struct output *o, unsigned char *atlas) {
    int swap=o->format==WL_SHM_FORMAT_XBGR8888 || o->format==WL_SHM_FORMAT_ABGR8888;
    for(int y=0;y<height;y++) {
        int sy=(o->buffers[o->front].flags & ZWLR_SCREENCOPY_FRAME_V1_FLAGS_Y_INVERT) ? height-y-1 : y;
        const unsigned char *src=o->buffers[o->front].pixels+(size_t)sy*o->stride;
        unsigned char *dst=atlas+((size_t)y*count*width+o->index*width)*4;
        if(!swap) memcpy(dst,src,width*4);
        else swizzle_row((uint32_t *)dst,(const uint32_t *)src,width);
    }
}
static void frame_failed(void *d, struct zwlr_screencopy_frame_v1 *f) {
    zwlr_screencopy_frame_v1_destroy(f); ((struct output *)d)->frame=NULL;
    fail("Wayland refused monitor capture (the session may be locked).");
}
static void damage(void *d, struct zwlr_screencopy_frame_v1 *f, uint32_t x,uint32_t y,uint32_t w,uint32_t h) {}
static void dmabuf(void *d, struct zwlr_screencopy_frame_v1 *f,uint32_t fmt,uint32_t w,uint32_t h) {}
static void buffer_done(void *d, struct zwlr_screencopy_frame_v1 *f) {
    struct output *o=d;
    if (o->buffers[o->back].buffer && !failed) {
        if(o->generation) zwlr_screencopy_frame_v1_copy_with_damage(f,o->buffers[o->back].buffer);
        else zwlr_screencopy_frame_v1_copy(f,o->buffers[o->back].buffer);
    }
    else fail("Compositor did not offer a shared-memory capture buffer.");
}
static const struct zwlr_screencopy_frame_v1_listener frame_listener = {
    frame_buffer,frame_flags,frame_ready,frame_failed,damage,dmabuf,buffer_done
};
/* Assemble only changed outputs directly into a reader-safe slot. Per-slot
   generations keep unchanged monitor pixels intact without copying them.
   Same three-slot protocol and nonblocking locks as frames.py. */
static int reserve_slot(void) {
    uint64_t current; memcpy(&current,shared+16,8);
    for (uint64_t slot=0;slot<3;slot++) {
        if (slot==current) continue;
        size_t offset=64+slot*(32+framebytes);
        struct flock lock={.l_type=F_WRLCK,.l_whence=SEEK_SET,.l_start=offset,.l_len=1};
        if (fcntl(framefd,F_SETLK,&lock)<0) continue;
        writing_slot=(int)slot; return 1;
    }
    return 0;
}
static void release_slot(void) {
    if(writing_slot<0) return;
    struct flock lock={.l_type=F_UNLCK,.l_whence=SEEK_SET,
        .l_start=64+writing_slot*(32+framebytes),.l_len=1};
    fcntl(framefd,F_SETLK,&lock); writing_slot=-1;
}
static void publish(void) {
    if(!reserve_slot()) return;
    size_t offset=64+writing_slot*(32+framebytes);
    double started=now(); uint64_t generations[5]={0};
    for(int i=0;i<noutputs;i++) if(outputs[i].index>=0) {
        struct output *o=&outputs[i]; int index=o->index;
        generations[index]=o->generation;
        if(o->generation!=published_generations[index] && o->captured<started) started=o->captured;
        if(slot_generations[writing_slot][index]!=o->generation) {
            copy_output(o,shared+offset+32);
            slot_generations[writing_slot][index]=o->generation;
        }
    }
    double captured=now(); uint64_t seq=sequence+1, slot=writing_slot;
    memcpy(shared+offset,&seq,8); memcpy(shared+offset+8,&started,8);
    memcpy(shared+offset+16,&captured,8); memcpy(shared+offset+24,&captured,8);
    if(flock(framefd,LOCK_EX|LOCK_NB)==0) {
        memcpy(shared,&seq,8); memcpy(shared+8,&captured,8); memcpy(shared+16,&slot,8);
        memcpy(shared+24,generations,40);
        memcpy(published_generations,generations,40);
        flock(framefd,LOCK_UN); sequence=seq; dirty=0;
    }
    release_slot();
}
int main(int argc,char **argv) {
    if (argc<6) return 2;
    width=atoi(argv[2]); height=atoi(argv[3]); int fps=atoi(argv[4]); count=argc-5;
    if(width<320 || height<180 || width>3840 || height>2160 || count>5 || width*count>16384 || fps<1 || fps>120) return 2;
    framebytes=(size_t)width*height*count*4;
    framefd=open(argv[1],O_RDWR|O_CLOEXEC);
    struct stat st;
    if(framefd<0 || fstat(framefd,&st)<0 || st.st_size!=(off_t)(64+3*(32+framebytes))) return 2;
    shared=mmap(NULL,st.st_size,PROT_READ|PROT_WRITE,MAP_SHARED,framefd,0);
    if(shared==MAP_FAILED) return 2;
    signal(SIGTERM,stop); signal(SIGINT,stop);
    struct wl_display *display=wl_display_connect(NULL);
    if(!display) { fail("Cannot connect to the host Wayland compositor."); return 1; }
    struct wl_registry *registry=wl_display_get_registry(display);
    wl_registry_add_listener(registry,&registry_listener,NULL);
    if(wl_display_roundtrip(display)<0 || wl_display_roundtrip(display)<0) return 1;
    if(!shm || !manager) { fail("This compositor does not support wlr-screencopy v3."); return 1; }
    for(int i=0;i<count;i++) {
        int found=0;
        for(int j=0;j<noutputs;j++) if(!strcmp(outputs[j].name,argv[5+i])) {
            outputs[j].index=i; found=1; break;
        }
        if(!found) { fail("Virtual monitor was not advertised over Wayland."); return 1; }
    }
    double next=now(), period=1./fps;
    while(running && !failed) {
        double t=now(), wake=t+.1;
        int all_ready=1;
        for(int i=0;i<noutputs;i++) if(outputs[i].index>=0 && !outputs[i].generation) all_ready=0;
        if(dirty && all_ready) {
            if(t>=next) {
                publish();
                next=t+period;
            }
            if(next<wake) wake=next;
        }
        for(int i=0;i<noutputs;i++) if(outputs[i].index>=0 && !outputs[i].frame) {
            struct output *o=&outputs[i];
            if(t>=o->next) {
                o->back=o->front==0 ? 1 : 0;
                o->buffers[o->back].flags=0;
                o->frame=zwlr_screencopy_manager_v1_capture_output(manager,1,o->wl);
                zwlr_screencopy_frame_v1_add_listener(o->frame,&frame_listener,o);
                o->next=t+period;
            } else if(o->next<wake) wake=o->next;
        }
        while(wl_display_prepare_read(display)!=0) {
            if(wl_display_dispatch_pending(display)<0) { failed=1; break; }
        }
        if(failed) break;
        int flushed=wl_display_flush(display);
        if(flushed<0 && errno!=EAGAIN) { wl_display_cancel_read(display); failed=1; break; }
        struct pollfd fds[2]={{wl_display_get_fd(display),POLLIN | (flushed<0 ? POLLOUT : 0),0},{STDIN_FILENO,POLLIN,0}};
        int timeout=(int)((wake-now())*1000+.5);
        if(timeout<1)timeout=1;
        if(timeout>100)timeout=100;
        int result=poll(fds,2,timeout);
        if(result>0 && (fds[0].revents&POLLIN)) {
            if(wl_display_read_events(display)<0) failed=1;
        } else wl_display_cancel_read(display);
        if(result<0 && errno!=EINTR) failed=1;
        if(fds[0].revents&(POLLHUP|POLLERR)) failed=1;
        if(fds[1].revents&(POLLIN|POLLHUP|POLLERR)) { char buf[64]; if(read(0,buf,sizeof(buf))<=0) running=0; }
        if(wl_display_dispatch_pending(display)<0) failed=1;
    }
    for(int i=0;i<noutputs;i++) {
        struct output *o=&outputs[i];
        if(o->frame) zwlr_screencopy_frame_v1_destroy(o->frame);
        for(int j=0;j<2;j++) {
            if(o->buffers[j].buffer) wl_buffer_destroy(o->buffers[j].buffer);
            if(o->buffers[j].pixels) munmap(o->buffers[j].pixels,o->buffers[j].size);
        }
        wl_output_destroy(o->wl);
    }
    zwlr_screencopy_manager_v1_destroy(manager); wl_shm_destroy(shm);
    wl_registry_destroy(registry); wl_display_disconnect(display);
    release_slot(); munmap(shared,st.st_size); close(framefd);
    return failed ? 1 : 0;
}
