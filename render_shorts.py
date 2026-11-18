"""Render the reviewed Shorts plan locally with FFmpeg; automatic source download; no AI API or upload.
Put this script and fiber_plan.json beside the repo's main.py.
Uses reviewed per-span framing; diagrams stay full-width by default.
"""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import urllib.request
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass


def stamp(t, ass=False):
    base = 100 if ass else 1000
    n = round(t * base)
    whole, frac = divmod(n, base)
    minutes, sec = divmod(whole, 60)
    hour, minute = divmod(minutes, 60)
    return f'{hour}:{minute:02}:{sec:02}.{frac:02}' if ass else f'{hour:02}:{minute:02}:{sec:02},{frac:03}'


def text_ass(text):
    return text.replace('\\', '/').replace('{', '(').replace('}', ')').replace('\n', r'\N')


def timed_captions(clip):
    offset = 0
    result = []
    for start, end in clip['spans']:
        for cue in clip['captions']:
            a, b = max(start, cue['start']), min(end, cue['end'])
            if b > a:
                result.append((offset+a-start, offset+b-start, cue['text']))
        offset += end-start
    return result


def write_captions(folder, clip, number):
    length = sum(b-a for a,b in clip['spans'])
    header = '''[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Label,Arial,20,&H00D8DFE8,&H00D8DFE8,&H00201007,&H00201007,0,0,0,0,100,100,2,0,1,0,0,5,45,45,0,1
Style: Title,Arial,42,&H00FFFFFF,&H00FFFFFF,&H00201007,&H00201007,-1,0,0,0,100,100,0,0,1,0,0,5,45,45,0,1
Style: Sub,Arial,38,&H00FFFFFF,&H00FFFFFF,&H00201007,&H00201007,-1,0,0,0,100,100,0,0,1,1,0,5,45,45,0,1
Style: Small,Arial,18,&H00B5B7BB,&H00B5B7BB,&H00201007,&H00201007,0,0,0,0,100,100,0,0,1,0,0,5,45,45,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    events = []
    def event(a,b,style,text,pos):
        events.append(f'Dialogue: 0,{stamp(a,True)},{stamp(b,True)},{style},,0,0,0,,{{\\pos(360,{pos})}}{text_ass(text)}')

    event(0,length,'Title',clip['title'],210)


    event(0,length,'Small','Nguồn: engineerguy',1065)

    captions = timed_captions(clip)
    for a,b,text in captions:
        # Allow ASS to wrap at word boundaries if the display font is wider.
        event(a,b,'Sub',text,930)
    (folder/'captions.ass').write_text(header+'\n'.join(events)+'\n',encoding='utf-8-sig')
    srt='\n\n'.join(f'{i}\n{stamp(a)} --> {stamp(b)}\n{text}' for i,(a,b,text) in enumerate(captions,1))
    (folder/(clip['id']+'.vi.srt')).write_text(srt+'\n',encoding='utf-8-sig')
    return length


def probe(path):
    p=subprocess.run(['ffprobe','-v','error','-show_format','-show_streams','-of','json',str(path)],capture_output=True,text=True,check=True)
    return json.loads(p.stdout)


def graph_for(clip):
    # Input is already seeked to the first cut. Trim times are relative to it.
    origin=clip['spans'][0][0]
    n=len(clip['spans'])
    parts=[]
    if n>1:
        parts += ['[0:v]split='+str(n)+''.join(f'[vin{i}]' for i in range(n)),
                  '[0:a]asplit='+str(n)+''.join(f'[ain{i}]' for i in range(n))]
    for i,(a,b) in enumerate(clip['spans']):
        v=f'vin{i}' if n>1 else '0:v'
        audio=f'ain{i}' if n>1 else '0:a'
        # Fractions of the original frame: x, y, width, height.
        # Only use a crop after reviewing the entire selected scene.
        crop = clip.get('framing', [[0, 0, 1, 1]] * n)[i]
        x, y, w, h = crop
        framing = (f'crop=w=trunc(iw*{w}/2)*2:h=trunc(ih*{h}/2)*2:'
                   f'x=trunc(iw*{x}/2)*2:y=trunc(ih*{y}/2)*2,'
                   'scale=720:540:force_original_aspect_ratio=decrease,'
                   'pad=720:540:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1')
        parts.append(f'[{v}]trim=start={a-origin:.3f}:end={b-origin:.3f},setpts=PTS-STARTPTS,fps=30,{framing}[v{i}]')
        parts.append(f'[{audio}]atrim=start={a-origin:.3f}:end={b-origin:.3f},asetpts=PTS-STARTPTS[a{i}]')
    if n>1:
        parts.append(''.join(f'[v{i}][a{i}]' for i in range(n))+f'concat=n={n}:v=1:a=1[vc][ac]')
        v,a='vc','ac'
    else:
        v,a='v0','a0'
    parts.append(f'[{v}]split=2[bgsrc][fgsrc]')
    parts.append('[bgsrc]scale=180:320:force_original_aspect_ratio=increase,crop=180:320,gblur=sigma=18,scale=720:1280,eq=brightness=-0.30:saturation=0.65[bg]')
    parts.append('[fgsrc]null[fg]')
    parts.append('[bg][fg]overlay=0:300,drawbox=x=0:y=0:w=iw:h=280:color=black@0.35:t=fill,drawbox=x=0:y=870:w=iw:h=135:color=black@0.55:t=fill,ass=captions.ass,format=yuv420p[vout]')
    parts.append(f'[{a}]aresample=48000,loudnorm=I=-16:TP=-1.5:LRA=9[aout]')
    return ';\n'.join(parts)


def validate(plan):
    for clip in plan['clips']:
        framing = clip.get('framing', [[0, 0, 1, 1]] * len(clip['spans']))
        if len(framing) != len(clip['spans']):
            raise ValueError('Each span must have one framing entry')
        for x, y, w, h in framing:
            if (not all(math.isfinite(v) for v in [x,y,w,h]) or
                    not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1) or
                    x+w > 1.000001 or y+h > 1.000001):
                raise ValueError('Crop outside source frame: '+clip['id'])
        previous=-1
        for a,b in clip['spans']:
            if not all(math.isfinite(x) for x in [a,b]) or not 0<=a<b<=plan['source_duration']+0.1 or a<previous:
                raise ValueError('Invalid edit range: '+clip['id'])
            previous=b
        for cue in clip['captions']:
            if not 0<=cue['start']<cue['end']<=plan['source_duration']+0.1:
                raise ValueError('Invalid subtitle timing')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,help='Override local video path')
    parser.add_argument('--preview-seconds',type=float,default=0,help='Render only the beginning of each clip for testing')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    for executable in ['ffmpeg','ffprobe']:
        if not shutil.which(executable):raise RuntimeError(executable+' not found. Reopen PowerShell.')
    plan=json.loads((root/'fiber_plan.json').read_text(encoding='utf-8'))
    validate(plan)
    source=(args.source or root/plan['source_relative']).resolve()
    if not args.source:
        alternatives=[source,source.with_suffix('.mkv'),source.with_suffix('.mp4')]
        source=next((p for p in alternatives if p.is_file()),source)
    if not source.is_file():
        if args.source:
            raise FileNotFoundError(str(source))
        source.parent.mkdir(parents=True,exist_ok=True)
        partial=source.with_suffix('.part')
        try:
            print('Downloading source (~20 MiB) to '+str(source),flush=True)
            req=urllib.request.Request(plan['source_url'],headers={'User-Agent':'ScienceShortsLocal/1.0'})
            with urllib.request.urlopen(req,timeout=30) as response, partial.open('wb') as f:
                shutil.copyfileobj(response,f)
            probe(partial)
            partial.replace(source)
        except Exception as e:
            partial.unlink(missing_ok=True)
            print('Wikimedia unavailable: '+str(e),flush=True)
            print('Trying the original creator YouTube upload once...',flush=True)
            import importlib.util
            if importlib.util.find_spec('yt_dlp') is None:
                raise RuntimeError('YouTube fallback needs yt-dlp in this venv. Or download Original file from '+plan['source_page']+' and save as '+str(source)) from e
            from yt_dlp import YoutubeDL
            target=source.with_suffix('.mkv')
            opts={'format':'bv*[height<=720]+ba/b[height<=720]',
                  'outtmpl':str(source.with_suffix('.%(ext)s')),
                  'merge_output_format':'mkv','noplaylist':True,
                  'retries':0,'fragment_retries':0,'socket_timeout':20,
                  'cachedir':False,'quiet':False,'overwrites':False}
            try:
                with YoutubeDL(opts) as downloader:
                    downloader.download([plan['youtube_url']])
            except Exception as error:
                raise RuntimeError('Both downloads unavailable. No automatic repeat. Save the creator video locally and use --source "PATH". Detail: '+str(error)) from error
            found=[p for p in [target,source.with_suffix('.mp4'),source] if p.is_file()]
            if not found:raise RuntimeError('Download ended without a usable video file.')
            source=found[0]
    info=probe(source)
    for kind in ['video','audio']:
        if not any(s['codec_type']==kind for s in info['streams']):raise RuntimeError('Missing '+kind+' stream')
    if not args.source and abs(float(info['format']['duration'])-plan['source_duration'])>3:
        raise RuntimeError('Source duration does not match the transcript. Check the video file.')
    if float(info['format']['duration'])<max(b for c in plan['clips'] for a,b in c['spans'])-0.1:
        raise RuntimeError('Source is shorter than the selected cuts. Check the input file.')
    label=datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    output=root/'output'/('fiber_vi_'+label)
    output.mkdir(parents=True,exist_ok=False)
    (output/'fiber_plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    completed=[]
    print('Rendering 2 science Shorts with original speech + Vietnamese captions. No API or upload.',flush=True)
    for number,clip in enumerate(plan['clips'],1):
        folder=output/clip['id'];folder.mkdir()
        length=write_captions(folder,clip,number)
        if args.preview_seconds>0:length=min(length,args.preview_seconds)
        (folder/'filter.txt').write_text(graph_for(clip),encoding='utf-8')
        (folder/'description.txt').write_text(clip['description']+'\n\n'+plan['source_page']+'\n'+plan['license_note'],encoding='utf-8')
        (folder/'title.txt').write_text(clip['upload_title'],encoding='utf-8')
        destination=folder/(clip['id']+'.mp4')
        begin=clip['spans'][0][0]
        bound=clip['spans'][-1][1]-begin
        command=['ffmpeg','-hide_banner','-nostdin','-y','-loglevel','warning',
            '-ss',str(begin),'-t',str(bound),'-i',str(source),
            '-filter_complex_threads','2','-filter_complex',graph_for(clip),
            '-map','[vout]','-map','[aout]','-t',str(length),
            '-c:v','libx264','-preset','fast','-crf','21','-threads','4',
            '-c:a','aac','-b:a','128k','-movflags','+faststart',
            '-progress','pipe:1','-nostats',str(destination)]
        print(f'\n[{number}/2] {clip["id"]}: {length:.2f}s',flush=True)
        with (folder/'render.log').open('w',encoding='utf-8') as log:
            proc=subprocess.Popen(command,cwd=folder,stdout=subprocess.PIPE,stderr=log,text=True,encoding='utf-8',errors='replace')
            last=-1
            try:
                for line in proc.stdout:
                    if line.startswith('out_time_us='):
                        try:percent=min(100,int(float(line.split('=',1)[1])/1e6/length*100))
                        except ValueError:continue
                        if percent//10!=last:
                            print(f'  {percent}%',flush=True);last=percent//10
                code=proc.wait()
            except BaseException:
                proc.terminate();proc.wait();raise
        if code:
            raise RuntimeError('FFmpeg failed. Send this log: '+str(folder/'render.log'))
        result=probe(destination)
        v=next(s for s in result['streams'] if s['codec_type']=='video')
        duration=float(result['format']['duration'])
        if not any(s['codec_type']=='audio' for s in result['streams']):
            raise RuntimeError('Output missing audio')
        if (v['width'],v['height'])!=(720,1280) or abs(duration-length)>0.5:
            raise RuntimeError('Output validation failed: '+str(destination))
        completed.append({'file':str(destination),'duration':duration,'width':v['width'],'height':v['height']})
        (output/'render_report.json').write_text(json.dumps(completed,indent=2),encoding='utf-8')
        print('  OK:',destination,flush=True)
    print('\nDONE. Your 2 MP4 files are inside:\n'+str(output),flush=True)
    print('Original English speech + Vietnamese captions. Read description.txt for source attribution. Nothing was uploaded.',flush=True)


if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:
        print('\nStopped.',file=sys.stderr);sys.exit(130)
    except Exception as error:
        print('\nERROR:',error,file=sys.stderr);sys.exit(1)

