"""Bidirectional, staged StepMania / osu!mania conversion.

StepMania parsing/timing is provided by simfile 2.1.1. Native StepMania ticks
are 1/48 beat. Unsupported gameplay is explicit, never silently dropped.
"""
from pathlib import Path
from collections import Counter, defaultdict
from bisect import bisect_right
import csv
import math
import os
import shutil
import subprocess
import tempfile
from zipfile import ZipFile, ZIP_DEFLATED
import simfile
from simfile.notes import Note, NoteData, NoteType
from simfile.notes.group import group_notes
from simfile.ssc import SSCSimfile, SSCChart
from simfile.timing import Beat, BeatValues, TimingData
from simfile.timing.engine import TimingEngine, EventTag
from simfile.timing._private.timingsource import timing_source

STYLES = {4:'dance-single', 5:'pump-single', 6:'dance-solo', 7:'kb7-single', 8:'dance-double', 10:'pump-double'}
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.webp'}
AUDIO_EXTS = {'.ogg', '.mp3', '.wav', '.flac'}


def number(value, label='number'):
    value = float(value)
    if not math.isfinite(value): raise ValueError(f'Invalid {label}')
    return value


def asset(folder, name, required=False):
    if not name:
        if required: raise ValueError('Chart has no music filename')
        return None
    root = Path(folder).resolve()
    path = (root / name.replace('\\', '/')).resolve()
    if not path.is_relative_to(root): raise ValueError(f'Attachment outside chart folder: {name}')
    if not path.is_file():
        if required: raise FileNotFoundError(f'Missing attachment: {name}')
        return None
    return path


def osu_background(core, sections, folder):
    for line in core.sec(sections, 'Events'):
        row = next(csv.reader([line]))
        if len(row) >= 3 and row[0].strip() in ('0', 'Background'):
            return asset(folder, row[2])
    return None


def catalog(core, source, direction):
    """List every difficulty; prefer SSC to an identically named SM companion."""
    if not str(source).strip(): raise ValueError('Choose a chart file or pack folder')
    root = Path(source).expanduser()
    if not root.exists(): raise FileNotFoundError('Choose an existing chart or pack folder')
    files = [root] if root.is_file() else sorted(p for p in root.rglob('*') if p.is_file())
    wanted = {'.sm', '.ssc'} if direction == 'sm_to_osu' else {'.osu'}
    files = [p for p in files if p.suffix.lower() in wanted]
    ssc = {str(p.with_suffix('')).casefold() for p in files if p.suffix.lower() == '.ssc'}
    result, errors = [], []
    for path in files:
        if path.suffix.lower() == '.sm' and str(path.with_suffix('')).casefold() in ssc: continue
        try:
            if direction == 'sm_to_osu':
                song = simfile.open(str(path))
                for i, chart in enumerate(song.charts):
                    data = NoteData(chart)
                    title = song.get('TITLE') or path.stem
                    version = song.get('SUBTITLE') or chart.get('DIFFICULTY') or f'Chart {i+1}'
                    creator = (chart.get('STEPARTIST') or chart.get('CREDIT') or
                               song.get('STEPARTIST') or song.get('CREDIT') or
                               chart.get('DESCRIPTION') or 'Unknown')
                    pack = path.resolve().parent.parent.name
                    result.append(dict(path=str(path.resolve()), index=i, title=title,
                        artist=song.get('ARTIST') or 'Unknown', creator=creator, pack=pack,
                        version=version, keys=data.columns, format=path.suffix.lower()[1:].upper(), meter=chart.get('METER') or '1'))
            else:
                info = core.read_header_info(str(path))
                if info: result.append(dict(info, index=0, format='osu!', meter=''))
        except Exception as error: errors.append(f'{path.name}: {error}')
    return result, errors


def ensure_objects(objects):
    ends = {}
    for start, column, end in sorted(objects):
        if start < 0: raise ValueError('Negative note timestamp after audio preparation')
        if end is not None and end <= start: raise ValueError('A hold collapses to zero length after conversion')
        if column in ends and start <= ends[column]:
            raise ValueError('Two notes or a hold/tap collide in the same lane after timing conversion')
        ends[column] = end if end is not None else start


def step_timing(song, chart):
    """Apply StepMania's own-timing/default rules before the library engine."""
    tags=('BPMS','STOPS','DELAYS','WARPS','OFFSET','TIMESIGNATURES','SCROLLS',
          'SPEEDS','FAKES','LABELS','TICKCOUNTS','COMBOS')
    own=isinstance(song,SSCSimfile) and float(song.get('VERSION') or 0)>=.7 and any(chart.get(key) for key in tags if key != 'OFFSET')
    source=chart if own else song
    defaults=[]
    if own and 'OFFSET' not in chart:
        chart['OFFSET']=song.get('OFFSET') or '0'
    if not source.get('BPMS'):
        source['BPMS']='0=60'
        defaults.append('Missing BPM segment uses StepMania\'s native 60 BPM default')
    values=source['BPMS'].split(',')
    beat,bpm=values[0].strip().split('=')
    if number(beat)!=0:
        values[0]='0='+bpm;source['BPMS']=','.join(values)
    return TimingData(song,chart),source,defaults


def sm_to_osu(core, info, rate=1, od=8, hp=5, approximate=False):
    song = simfile.open(info['path']); chart = song.charts[info['index']]
    timing, source, defaults = step_timing(song, chart)
    if not timing.bpms or any(v.value <= 0 for v in timing.bpms):
        raise ValueError('Nonpositive/legacy negative BPMs are not supported; normalize them to SSC warps first')
    if 'routine' in chart.get('STEPSTYPE', '') or 'couple' in chart.get('STEPSTYPE', ''):
        raise ValueError('Multiplayer routine/couple charts cannot map to one mania player')
    data = NoteData(chart); keys = data.columns
    if not 1 <= keys <= 18: raise ValueError(f'osu!mania cannot represent {keys} lanes')
    engine = TimingEngine(timing)
    fakes = BeatValues.from_str(source.get('FAKES'))
    warnings, counts, objects = list(defaults), Counter(), []
    for group in group_notes(data, join_heads_to_tails=True):
        for note in group:
            beat = note.beat.round_to_tick()
            if note.keysound_index is not None: raise ValueError('Keysounded notes require audio mixing; this chart is unsupported')
            if not engine.hittable(beat) or any(start <= beat < start+Beat(length) for start, length in fakes):
                counts['unjudged warp/fake notes omitted'] += 1; continue
            kind = note.note_type
            if kind in (NoteType.MINE, NoteType.FAKE):
                if kind == NoteType.MINE and not approximate: raise ValueError('Mines have no mania equivalent; enable gameplay approximations to omit them')
                counts['mines/fakes omitted'] += 1; continue
            if kind in (NoteType.KEYSOUND, NoteType.ATTACK): raise ValueError('Auto keysounds need audio mixing and cannot be copied as taps')
            if kind in (NoteType.ROLL_HEAD, NoteType.LIFT):
                if not approximate: raise ValueError('Roll/lift judgments have no mania equivalent; enable gameplay approximations')
                counts['rolls converted to holds' if kind == NoteType.ROLL_HEAD else 'lifts converted to taps'] += 1
            start = float(engine.time_at(beat)) / rate
            end = float(engine.time_at(note.tail_beat.round_to_tick())) / rate if hasattr(note, 'tail_beat') else None
            objects.append((start, note.column, end))
    if not objects: raise ValueError('No playable notes in this difficulty')
    pad = max(0, math.ceil(-min(o[0] for o in objects)*1000)/1000)
    objects = [(round((s+pad)*1000), c, round((e+pad)*1000) if e is not None else None) for s,c,e in objects]
    ensure_objects(objects)
    red = {}
    signatures = source.get('TIMESIGNATURES') or '0=4=4'
    signatures = [tuple(number(p) for p in entry.strip().split('=')) for entry in signatures.split(',') if entry.strip()]
    def meter(beat):
        matches = [n for b,n,d in signatures if b <= float(beat)]
        return int(matches[-1]) if matches else 4
    for beat, bpm in timing.bpms:
        red[(float(engine.time_at(beat, EventTag.BPM))/rate+pad)*1000] = (60000/(float(bpm)*rate), meter(beat))
    # Reset beat origins after pauses/warps without inventing zero/infinite BPM.
    for entries, ending in ((timing.stops, EventTag.STOP_END), (timing.delays, EventTag.DELAY_END)):
        for beat,_ in entries:
            red[(float(engine.time_at(beat, ending))/rate+pad)*1000] = (60000/(float(engine.bpm_at(beat))*rate), meter(beat))
    for beat, length in timing.warps:
        end = beat + Beat(length)
        red[(float(engine.time_at(end))/rate+pad)*1000] = (60000/(float(engine.bpm_at(end))*rate), meter(end))
    if timing.stops or timing.delays or timing.warps:
        warnings.append('Stops/delays/warps baked into note timestamps; mania has no identical native pause/warp scrolling')
    if any(d != 4 for _,_,d in signatures):
        warnings.append('Time-signature denominator has no direct mania equivalent; barlines may differ')
    for beat,_,_ in signatures:
        b = Beat(beat).round_to_tick()
        red[(float(engine.time_at(b))/rate+pad)*1000] = (60000/(float(engine.bpm_at(b))*rate), meter(b))
    timing_lines = [(t, f'{t:.6f},{bl:.9f},{m},1,0,100,1,0') for t,(bl,m) in red.items()]
    scrolls = BeatValues.from_str(source.get('SCROLLS')) or [(Beat(0), 1)]
    speeds = []
    for entry in (source.get('SPEEDS') or '0=1=0=0').split(','):
        if not entry.strip(): continue
        b, ratio, duration, unit = (number(v) for v in entry.strip().split('='))
        if duration != 0:
            if not approximate: raise ValueError('Animated speed ramps have no exact mania SV equivalent; enable approximations')
            warnings.append('Animated speed ramp approximated as an instantaneous SV change')
        speeds.append((Beat(b).round_to_tick(), ratio))
    for beat in sorted({b for b,_ in scrolls} | {b for b,_ in speeds}):
        scroll = next((float(v) for b,v in reversed(scrolls) if b <= beat), 1)
        speed = next((float(v) for b,v in reversed(speeds) if b <= beat), 1)
        ratio = scroll * speed
        if not .1 <= ratio <= 10:
            if not approximate: raise ValueError('Zero/reverse/extreme scrolling cannot be preserved in stable mania; enable approximations')
            warnings.append('Zero/reverse/extreme scroll multiplier omitted'); continue
        t = (float(engine.time_at(beat))/rate+pad)*1000
        timing_lines.append((t, f'{t:.6f},{-100/ratio:.9f},4,1,0,100,0,0'))
    music = chart.get('MUSIC') or song.get('MUSIC')
    folder = Path(info['path']).parent
    if not music:
        candidates=[p for p in folder.iterdir() if p.suffix.lower() in AUDIO_EXTS]
        if len(candidates)==1: music=candidates[0].name
    audio = asset(folder, music, True)
    background_name = song.get('BACKGROUND') or song.get('JACKET') or song.get('BANNER')
    background = asset(folder, background_name)
    if background and background.suffix.lower() not in IMAGE_EXTS:
        warnings.append('Non-image background omitted'); background = None
    if background_name and not background: warnings.append('Background asset missing; exported without a background')
    if song.get('BGCHANGES'): warnings.append('Dynamic background events flattened to the static background')
    if song.get('ATTACKS') or chart.get('ATTACKS'):
        if not approximate: raise ValueError('Gameplay attacks require approximations; they cannot be reproduced in mania')
        warnings.append('Gameplay attacks omitted')
    preview = number(song.get('SAMPLESTART') or -1)
    preview = round((preview/rate+pad)*1000) if preview >= 0 else -1
    version = info['version']
    if rate != 1: version += f' x{core.fmt_rate(rate)}'
    od = number(chart.get('JATOTRAINEROD') or od); hp = number(chart.get('JATOTRAINERHP') or hp)
    for label,value in (('OD',od),('HP',hp)):
        if not 0 <= value <= 10: raise ValueError(f'{label} must be 0–10')
    warnings += [f'{value} {label}' for label,value in counts.items()]
    if pad: warnings.append(f'Audio padded by {pad:.3f}s to preserve notes before music zero')
    return dict(kind='osu', info=info, song=song, audio=audio, background=background, pad=pad,
        preview=preview, version=version, keys=keys, od=od, hp=hp, objects=objects,
        timing=[line for _,line in sorted(timing_lines, key=lambda x:x[0])], warnings=warnings, sync_error=.5)


def osu_to_sm(core, info, rate=1, strict=True, meter=12, approximate=False):
    _, sections = core.parse_osu(info['path']); general=core.sec(sections,'General'); md=core.sec(sections,'Metadata'); diff=core.sec(sections,'Difficulty')
    keys = int(number(core.kv(diff,'CircleSize') or 4))
    if keys not in STYLES: raise ValueError(f'{keys}K has no supported standard StepMania style (4/5/6/7/8/10K supported)')
    red, sv, warnings = {}, [], []
    for line in core.sec(sections, 'TimingPoints'):
        if not line.strip() or line.startswith('//'): continue
        fields = line.split(','); t=number(fields[0])/1000; length=number(fields[1])
        inherited = fields[6].strip() == '0' if len(fields)>6 else length<0
        if inherited:
            if length < 0: sv.append((t, -100/length))
        else:
            if length<=0: raise ValueError('Invalid osu! BPM timing point')
            red[t] = (60/length*1000, int(fields[2]) if len(fields)>2 else 4)
    if not red: raise ValueError('Chart has no BPM timing points')
    points = sorted((t,bpm,m) for t,(bpm,m) in red.items())
    raw=[]
    for line in core.sec(sections,'HitObjects'):
        if not line.strip(): continue
        p=line.split(','); t=number(p[2])/1000; kind=int(p[3]); col=min(keys-1,max(0,int(number(p[0])*keys/512)))
        if kind & 128: end=number(p[5].split(':')[0])/1000
        elif kind & 1: end=None
        else: raise ValueError('Only mania tap and hold objects are supported')
        sample=(p[5].split(':',1)[1] if kind & 128 else p[-1]).split(':',4)
        if len(sample)==5 and sample[-1].strip():
            if not approximate: raise ValueError('Custom hitsound files cannot be preserved as StepMania notes without keysound mixing')
            warnings.append('Custom hitsound attachment omitted')
        raw.append((t,col,end))
    if not raw: raise ValueError('Empty chart')
    # Choose an origin before all judgments, retaining the first red-point phase.
    anchor=points[0][0]; first_length=60/points[0][1]
    if min(t for t,_,_ in raw)<anchor:
        anchor -= math.ceil((anchor-min(t for t,_,_ in raw))/(4*first_length))*4*first_length
    points = [(anchor,points[0][1],points[0][2])] + [p for p in points if p[0]>anchor]
    times=[p[0] for p in points]; beats=[0.]
    for i in range(1,len(points)):
        beats.append(beats[-1]+(points[i][0]-points[i-1][0])*points[i-1][1]/60)
    def beat_at(t):
        i=max(0,bisect_right(times,t)-1)
        return Beat(beats[i]+(t-times[i])*points[i][1]/60).round_to_tick()
    result=SSCSimfile.blank(); result['TITLE']=core.kv(md,'TitleUnicode') or core.kv(md,'Title') or info['title']
    result['TITLETRANSLIT']=core.kv(md,'Title') or info['title']
    result['ARTIST']=core.kv(md,'ArtistUnicode') or core.kv(md,'Artist') or info.get('artist','Unknown')
    result['ARTISTTRANSLIT']=core.kv(md,'Artist') or info.get('artist','Unknown')
    result['ORIGIN']=core.kv(md,'Source') or ''
    result['SUBTITLE']=core.kv(md,'Version') or info['version']
    if rate!=1: result['SUBTITLE'] += f' x{core.fmt_rate(rate)}'
    result['CREDIT']=core.kv(md,'Creator') or info['creator']; result['OFFSET']=f'{-anchor/rate:.9f}'
    preview=number(core.kv(general,'PreviewTime') or -1)/1000
    result['SAMPLESTART']=f'{max(0,preview/rate):.6f}'; result['SAMPLELENGTH']=f'{12/rate:.6f}'
    result['BPMS']=','.join(f'{Beat(b).round_to_tick()}={bpm*rate:.9f}' for b,(_,bpm,_) in zip(beats,points))
    result['TIMESIGNATURES']=','.join(f'{Beat(b).round_to_tick()}={m}=4' for b,(_,_,m) in zip(beats,points))
    result['SCROLLS']=','.join(f'{beat_at(t)}={ratio:.9f}' for t,ratio in sv) or '0=1'
    notes=[]; taken=set(); pairs=[]
    for t,col,end in raw:
        b=beat_at(t); notes.append(Note(b,col,NoteType.HOLD_HEAD if end is not None else NoteType.TAP)); pairs.append((b,t))
        for row,kind in ((b,'head'),) + ((beat_at(end),'tail'),) if end is not None else ((b,'head'),):
            if (row,col) in taken: raise ValueError('StepMania tick quantization collides notes in one lane; cannot preserve the chart')
            taken.add((row,col))
        if end is not None:
            tail=beat_at(end)
            if tail<=b: raise ValueError('Hold becomes zero length on StepMania tick grid')
            notes.append(Note(tail,col,NoteType.TAIL)); pairs.append((tail,end))
    chart=SSCChart.blank(); chart['STEPSTYPE']=STYLES[keys]; chart['CHARTNAME']=result['SUBTITLE']
    chart['DESCRIPTION']=chart['CHARTNAME']; chart['CREDIT']=result['CREDIT']; chart['DIFFICULTY']='Edit'; chart['METER']=str(int(meter))
    chart['JATOTRAINEROD']=core.kv(diff,'OverallDifficulty') or '8'; chart['JATOTRAINERHP']=core.kv(diff,'HPDrainRate') or '5'
    chart['NOTES']=str(NoteData.from_notes(sorted(notes),keys)); result.charts.append(chart)
    engine=TimingEngine(TimingData(result))
    error=max(abs(float(engine.time_at(b))-t/rate)*1000 for b,t in pairs)
    if strict and error>2:
        raise ValueError(f'StepMania tick grid would shift judgments by up to {error:.3f} ms; allow quantization to export')
    if error>.5: warnings.append(f'StepMania tick-grid sync deviation up to {error:.3f} ms')
    if sv: warnings.append('Mania SV exported as StepMania SCROLLS; appearance also depends on the player speed mod')
    if any(l.startswith(('1,','Video,','Sprite,','Animation,')) for l in core.sec(sections,'Events')):
        warnings.append('Video/storyboard flattened to a static background')
    folder=Path(info['path']).parent
    return dict(kind='ssc', info=info, song=result, chart=chart, keys=keys, version=chart['CHARTNAME'],
        audio=asset(folder,core.kv(general,'AudioFilename'),True), background=osu_background(core,sections,folder),
        pad=0, warnings=sorted(set(warnings)), sync_error=error)


def convert(core, entries, output, direction, rate=1, pitch=True, od=8, hp=5, meter=12,
            strict=True, approximate=False, ffmpeg=None, report=lambda p,s:None):
    """Prepare complete song folders before publishing; never overwrite sources."""
    rate=number(rate,'rate'); od=number(od,'OD'); hp=number(hp,'HP')
    if not .1<=rate<=5: raise ValueError('Rate must be between 0.1 and 5')
    if not 0<=od<=10 or not 0<=hp<=10: raise ValueError('OD/HP must be 0–10')
    if not 1<=int(meter)<=99: raise ValueError('StepMania meter must be 1–99')
    if not entries: raise ValueError('Choose at least one difficulty')
    if not str(output).strip(): raise ValueError('Choose an output folder')
    output=Path(output).expanduser().resolve()
    if not output.is_dir(): raise ValueError('Choose an existing output folder')
    converted, failures, paths, warnings = [], [], [], []
    for i,info in enumerate(entries):
        try:
            model=sm_to_osu(core,info,rate,od,hp,approximate) if direction=='sm_to_osu' else osu_to_sm(core,info,rate,strict,meter,approximate)
            converted.append(model)
        except Exception as error:
            failures.append(f"{info['title']} [{info['version']}]: {error}")
        report(.35*(i+1)/len(entries), f"Read {info['title']} [{info['version']}]")
    groups=defaultdict(list)
    for m in converted:
        # SM can share chart-specific timing, but song-level background/preview are shared.
        s=m['song']; preview=m.get('preview',s.get('SAMPLESTART'))
        key=(str(Path(m['info']['path']).parent),s.get('TITLE'),s.get('ARTIST'),
             str(m['audio']),str(m['background']),m['pad'],preview,
             (s.get('SUBTITLE'),s.get('ORIGIN')) if m['kind']=='ssc' else m['info'].get('pack'))
        groups[key].append(m)
    with tempfile.TemporaryDirectory(prefix='jatotrainer-convert-') as tmp:
        stage=Path(tmp)
        for index, models in enumerate(groups.values()):
            folder=stage/f'song-{index}';folder.mkdir()
            try:
                first=models[0]; title=first['song'].get('TITLE') or first['info']['title']; artist=first['song'].get('ARTIST') or first['info']['artist']
                media_cache={}
                def media(m):
                    key=(str(m['audio']),m['pad'])
                    if key in media_cache:return media_cache[key]
                    suffix=m['audio'].suffix if rate==1 and not m['pad'] else '.wav' if m['pad'] else '.mp3'
                    name='audio'+('' if not media_cache else f' {len(media_cache)+1}')+suffix
                    dest=folder/name
                    if rate==1 and not m['pad']:shutil.copyfile(m['audio'],dest)
                    else:
                        if not ffmpeg:raise ValueError('FFmpeg is required for rates and negative-time audio padding')
                        intermediate=folder/'_rate.mp3'
                        if rate==1: intermediate=m['audio']
                        else:core.make_audio(ffmpeg,str(m['audio']),str(intermediate),rate,pitch)
                        if m['pad']:
                            command=[ffmpeg,'-hide_banner','-loglevel','error','-y','-i',str(intermediate),'-af',f"adelay={m['pad']*1000:.6f}:all=1",'-c:a','pcm_s16le',str(dest)]
                            process=subprocess.run(command,capture_output=True)
                            if process.returncode:raise RuntimeError(process.stderr.decode(errors='replace')[-500:])
                        else:shutil.move(intermediate,dest)
                        if rate!=1 and intermediate.exists():intermediate.unlink()
                    media_cache[key]=name;return name
                bg=''
                if first['background']:
                    bg='background'+first['background'].suffix
                    if first['background'].suffix.lower() not in ('.png','.jpg','.jpeg','.bmp'):
                        from PIL import Image
                        bg='background.png'
                        with Image.open(first['background']) as image: image.convert('RGBA').save(folder/bg)
                    else:shutil.copyfile(first['background'],folder/bg)
                if direction=='sm_to_osu':
                    used=set()
                    for m in models:
                        audio=media(m); info=m['info']; song=m['song']
                        version=m['version']; base=version; n=2
                        while version.casefold() in used:version=f'{base} ({n})';n+=1
                        used.add(version.casefold())
                        clean=lambda v:str(v).replace('\r',' ').replace('\n',' ')
                        title_plain=song.get('TITLETRANSLIT') or song.get('TITLE') or info['title']
                        pack = info.get('pack') or ''
                        artist_plain=song.get('ARTISTTRANSLIT') or song.get('ARTIST') or info['artist']
                        event=f'0,0,"{bg}",0,0\r\n' if bg else ''
                        text='osu file format v14\r\n\r\n[General]\r\n'+f'AudioFilename:{audio}\r\nPreviewTime:{m["preview"]}\r\nMode:3\r\nSampleSet:Normal\r\n\r\n[Metadata]\r\n'
                        for k,v in dict(Title=title_plain,TitleUnicode=title,Artist=artist_plain,ArtistUnicode=artist,Creator=info['creator'],Version=version,BeatmapID=0,BeatmapSetID=-1,Source=pack,Tags=' '.join(dict.fromkeys([*pack.split(), 'jatotrainer']))).items():text+=f'{k}:{clean(v)}\r\n'
                        text+=f'\r\n[Difficulty]\r\nHPDrainRate:{m["hp"]:g}\r\nCircleSize:{m["keys"]}\r\nOverallDifficulty:{m["od"]:g}\r\nApproachRate:5\r\nSliderMultiplier:1.4\r\nSliderTickRate:1\r\n\r\n[Events]\r\n{event}\r\n[TimingPoints]\r\n'+'\r\n'.join(m['timing'])+'\r\n\r\n[HitObjects]\r\n'
                        for start,col,end in m['objects']:
                            x=math.floor((col+.5)*512/m['keys'])
                            text+=f'{x},192,{start},'+(f'128,0,{end}:0:0:0:0:' if end is not None else '1,0,0:0:0:0:')+'\r\n'
                        filename=core.safe_name(f'{artist_plain} - {title_plain} ({info["creator"]}) [{version}]')[:170]+'.osu'
                        n=2;stem=Path(filename).stem
                        while (folder/filename).exists():filename=f'{stem} ({n}).osu';n+=1
                        (folder/filename).write_bytes(text.encode('utf-8'))
                else:
                    merged=first['song']; merged.charts=[];merged['MUSIC']=media(first);merged['BACKGROUND']=bg
                    used=set()
                    for m in models:
                        chart=m['chart']; chart['MUSIC']=media(m)
                        # Set all timing fields for independent per-chart timing, even empty ones.
                        for field in ('BPMS','STOPS','DELAYS','WARPS','OFFSET','TIMESIGNATURES','SCROLLS','SPEEDS','FAKES'):
                            chart[field]=m['song'].get(field) or ('0' if field=='OFFSET' else '')
                        name=chart['CHARTNAME'];n=2
                        while chart['CHARTNAME'] in used:chart['CHARTNAME']=f'{name} ({n})';n+=1
                        used.add(chart['CHARTNAME']);merged.charts.append(chart)
                    (folder/'charts.ssc').write_bytes(str(merged).encode('utf-8'))
                label=f'{artist} - {title}'
                if direction=='osu_to_sm':label+=f" [{first['song']['SUBTITLE']}]"
                preferred=core.safe_name(label)[:100]+f' [jt x{core.fmt_rate(rate)}]'
                target=output
                if direction=='osu_to_sm' and first['song'].get('ORIGIN'):
                    pack=core.safe_name(first['song']['ORIGIN'])[:100].rstrip(' .')
                    if pack and target.name.casefold()!=pack.casefold():
                        target=output/pack
                        if not target.resolve().is_relative_to(output):raise ValueError('Pack folder is outside the output folder')
                        target.mkdir(exist_ok=True)
                if direction=='sm_to_osu':
                    # Finish the archive before exposing it to osu!'s import watcher.
                    with tempfile.NamedTemporaryFile(dir=target,suffix='.tmp',delete=False) as handle:
                        archive=Path(handle.name)
                    try:
                        with ZipFile(archive,'w',ZIP_DEFLATED) as z:
                            for file in sorted(folder.iterdir()):z.write(file,file.name)
                        dest=target/f'{preferred}.osz';n=2
                        while dest.exists():dest=target/f'{preferred} ({n}).osz';n+=1
                        os.replace(archive,dest)
                    finally:
                        archive.unlink(missing_ok=True)
                else:
                    dest=target/preferred;n=2
                    while dest.exists():dest=target/f'{preferred} ({n})';n+=1
                    dest.mkdir()
                    try:
                        for file in folder.iterdir():shutil.copyfile(file,dest/file.name)
                    except BaseException:shutil.rmtree(dest);raise
                paths.append(str(dest))
                for m in models:
                    warnings.extend(f"{m['info']['title']} [{m['version']}]: {w}" for w in m['warnings'])
                    report(.35+.65*(index+1)/len(groups),f"Saved {m['info']['title']} [{m['version']}] · sync deviation ≤{m['sync_error']:.3f} ms")
            except Exception as error:
                failures.extend(f"{m['info']['title']} [{m['version']}]: {error}" for m in models)
    report(1,f'Finished: {len(paths)} export(s); {len(failures)} rejected difficulty(s)')
    return dict(paths=paths,warnings=warnings,failures=failures,charts=len(entries)-len(failures))
