"""Pack export: stage complete output before publishing a new Songs folder."""
import csv
import hashlib
import subprocess
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata


def plain_title(value):
    value = unicodedata.normalize('NFKD', value).encode('ascii', 'ignore').decode().strip()
    return value or 'Pack'


def parse_rates(text):
    result = []
    for token in re.split(r'[,;\s]+', text.strip()):
        if not token:
            continue
        try:
            rate = float(token.rstrip('xX'))
        except ValueError:
            raise ValueError(f'Invalid rate: {token}')
        if not math.isfinite(rate) or not .1 <= rate <= 5:
            raise ValueError('Rates must be between 0.1 and 5 (1 = original).')
        if rate not in result:
            result.append(rate)
    if not result:
        raise ValueError('Choose at least one rate for each chart (1 = original).')
    return result


def safe_source(folder, filename):
    path = (folder / filename.replace('\\', '/')).resolve()
    if not path.is_relative_to(folder.resolve()) or not path.is_file():
        raise ValueError(f'Missing or invalid attached file: {filename}')
    return path


def validate_settings(core, pack_name, creator, od, hp):
    pack_name, creator = pack_name.strip(), creator.strip()
    if not pack_name or not creator or any(c in pack_name+creator for c in '\r\n'):
        raise ValueError('Enter a pack name and creator on a single line.')
    for label, value in [('OD', od), ('HP', hp)]:
        try:
            n = float(value)
        except ValueError:
            raise ValueError(f'{label} must be a number between 0 and 10.')
        if not math.isfinite(n) or not 0 <= n <= 10:
            raise ValueError(f'{label} must be between 0 and 10.')
    name = core.safe_name('Various Artists - '+pack_name)
    if not name or len(name) > 160:
        raise ValueError('Use a shorter pack name (up to 140 characters).')
    return pack_name, creator, float(od), float(hp), name


def audio_bitrate(ffmpeg, path):
    """Read the audio stream's reported kbps, using FFmpeg (no ffprobe)."""
    if not ffmpeg:
        return None
    flags=0x08000000 if os.name=='nt' else 0
    result=subprocess.run([ffmpeg,'-hide_banner','-i',str(path)],capture_output=True,
                          creationflags=flags,timeout=20)
    output=result.stderr.decode('utf-8','replace')
    stream=next((line for line in output.splitlines() if 'Audio:' in line),'')
    match=re.search(r'(\d+) kb/s',stream)
    if not match:
        match=re.search(r'Duration:.*bitrate:\s*(\d+) kb/s',output)
    return int(match.group(1)) if match else None


def target_bitrate(quality, source_bitrate):
    ceiling=min(320,source_bitrate or 320)
    choices=[32,40,48,56,64,80,96,112,128,160,192,224,256,320]
    if quality=='Original':requested=ceiling
    else:
        try:requested=int(str(quality).replace(' kbps',''))
        except ValueError:raise ValueError('Choose Original or an audio bitrate from 128 to 320 kbps.')
        if not 128<=requested<=320:raise ValueError('Audio compression must be between 128 and 320 kbps.')
        requested=min(requested,ceiling)
    return max((n for n in choices if n<=requested),default=32)


def background_path(core,info):
    _,sections=core.parse_osu(info['path'])
    for line in core.sec(sections,'Events'):
        row=next(csv.reader([line]))
        if len(row)>=3 and row[0].strip() in ('0','Background'):
            return safe_source(Path(info['path']).resolve().parent,row[2])
    return None


def build_pack(core, songs, pack_name, creator, od, hp, charts, ffmpeg, pitch=False, report=lambda *args: None, various_artists=False, audio_quality="Original", backgrounds_8bit=False, include_artist_in_diffname=False):
    pack_name, creator, od, hp, folder_name = validate_settings(core, pack_name, creator, od, hp)
    songs = Path(songs).resolve()
    if not songs.is_dir():
        raise ValueError('Choose your osu! Songs folder.')
    destination = songs / folder_name
    if destination.exists():
        raise ValueError(f'Folder already exists: {folder_name}. Choose a new pack name.')
    if not charts:
        raise ValueError('Add at least one chart.')
    entries=[]
    for chart in charts:
        info, rates = chart[:2]
        options = chart[2] if len(chart)>2 else {}
        checked = parse_rates(','.join(str(r) for r in rates))
        entries.append((info, checked, dict(options)))
    total = sum(len(rates) for _, rates, _ in entries)
    completed=0
    # Work outside Songs so osu! cannot import an incomplete pack during conversion.
    with tempfile.TemporaryDirectory(prefix='jatotrainer-pack-') as temporary:
        stage=Path(temporary)
        names=set()
        shared_backgrounds={}
        bitrate_cache={}
        def unique(name):
            stem,ext=os.path.splitext(name)
            candidate=name;number=2
            while candidate.casefold() in names:
                candidate=f'{stem} ({number}){ext}';number+=1
            names.add(candidate.casefold())
            return candidate
        for info,rates,options in entries:
            source=Path(info['path']).resolve();folder=source.parent
            header,sections=core.parse_osu(str(source))
            if core.kv(core.sec(sections,'General'),'Mode') != '3':
                raise ValueError('Pack maker supports osu!mania charts only.')
            meta=core.sec(sections,'Metadata')
            title=core.kv(meta,'Title') or info['title']
            charter=core.kv(meta,'Creator') or info['creator']
            artist=options.get('artist',core.kv(meta,'Artist') or info.get('artist','?'))
            original_unicode=core.kv(meta,'ArtistUnicode')
            artist_unicode=options.get('artist_unicode',original_unicode if original_unicode is not None else artist)
            use_various=options.get('various_artists',various_artists)
            diff_artist=artist
            if use_various:artist=artist_unicode='Various Artists'
            base_version=options.get('diffname') or f'{title} [{charter}]'
            if use_various and include_artist_in_diffname:
                prefix=diff_artist+' - '
                if not base_version.startswith(prefix):base_version=prefix+base_version
            tags=options.get('tags')
            for label,value in [('Artist',artist),('ArtistUnicode',artist_unicode),('Diffname',base_version),('Tags',tags or '')]:
                if any(c in value for c in '\r\n') or (label not in ('Tags','ArtistUnicode') and not value.strip()):
                    raise ValueError(f'{label} must be nonempty and on a single line.')
            chart_pitch=bool(options.get('pitch',pitch))
            original_audio=core.kv(core.sec(sections,'General'),'AudioFilename')
            audio_source=safe_source(folder,original_audio or '')
            if any(p.suffix.lower()=='.osb' for p in folder.iterdir()):
                raise ValueError(f'{title}: external storyboards require extra attachments; use a chart without its .osb.')
            backgrounds=[]
            events=core.sec(sections,'Events')
            for i,line in enumerate(events):
                if not line.strip() or line.lstrip().startswith('//'):
                    continue
                row=next(csv.reader([line]))
                kind=row[0].strip()
                if kind in ('0','Background') and len(row)>=3:
                    backgrounds.append((i,row,safe_source(folder,row[2])))
                elif kind in ('1','Video','Sprite','Animation','Sample','4','5','6'):
                    raise ValueError(f'{title}: video/storyboard/sample attachments need more than the three pack files; use a chart without them.')
            if not backgrounds:
                raise ValueError(f'{title}: no background image in [Events].')
            # Reject custom sample references rather than exporting charts with missing files.
            for line in core.sec(sections,'HitObjects'):
                fields=line.split(',')
                sample=(fields[5].split(':',1)[1] if len(fields)>5 and int(fields[3])&128 else fields[-1]) if len(fields)>=6 else ''
                parts=sample.split(':',4)
                if len(parts)==5 and parts[4].strip():
                    raise ValueError(f'{title}: custom hitsound file {parts[4]} is outside the three-file pack export.')
            stem=core.safe_name(title)[:100] or 'Song'
            bg_names={}
            for i,row,bg_source in backgrounds:
                source_key=str(bg_source)
                digest=hashlib.sha256(bg_source.read_bytes()).hexdigest()
                key=(digest,backgrounds_8bit)
                if key not in shared_backgrounds:
                    filename=unique(stem+('.png' if backgrounds_8bit else bg_source.suffix))
                    if backgrounds_8bit:
                        from PIL import Image
                        with Image.open(bg_source) as image:
                            image.convert('RGBA').quantize(colors=256,method=Image.Quantize.FASTOCTREE).save(stage/filename,format='PNG',optimize=True)
                    else:shutil.copyfile(bg_source,stage/filename)
                    shared_backgrounds[key]=filename
                bg_names[source_key]=shared_backgrounds[key]
            needs_encoding=any(rate!=1 for rate in rates) or audio_quality!='Original'
            source_kbps=None
            if needs_encoding and ffmpeg:
                if str(audio_source) not in bitrate_cache:
                    bitrate_cache[str(audio_source)]=audio_bitrate(ffmpeg,audio_source)
                source_kbps=bitrate_cache[str(audio_source)]
                if source_kbps is None and audio_quality!='Original':
                    raise ValueError(f'{title}: source bitrate could not be read; use Original quality.')
            bitrate=target_bitrate(audio_quality,source_kbps)
            for rate in rates:
                suffix='' if rate==1 else f' x{core.fmt_rate(rate)}'
                copy_audio=rate==1 and audio_quality=='Original'
                audio_name=unique(stem+suffix+(audio_source.suffix if copy_audio else '.mp3'))
                if rate==1:
                    if copy_audio:shutil.copyfile(audio_source,stage/audio_name)
                    else:
                        if not ffmpeg:raise ValueError("FFmpeg is required for audio compression.")
                        core.make_audio(ffmpeg,str(audio_source),str(stage/audio_name),1,False,bitrate=bitrate,allow_original=True)
                    output_sections=[(n,list(lines)) for n,lines in sections]
                else:
                    if not ffmpeg:
                        raise ValueError('FFmpeg is required for chart rates. Install the requirements or use rate 1.')
                    text,_,_,_=core.build_rate(header,sections,rate,'{diff}',False,audio_name,od)
                    _,output_sections=core.parse_osu_text(text)
                    core.make_audio(ffmpeg,str(audio_source),str(stage/audio_name),rate,chart_pitch,bitrate=bitrate)
                general=core.sec(output_sections,'General');metadata=core.sec(output_sections,'Metadata')
                difficulty=core.sec(output_sections,'Difficulty');output_events=core.sec(output_sections,'Events')
                for i,line in enumerate(output_events):
                    if not line.strip() or line.lstrip().startswith('//'):
                        continue
                    row=next(csv.reader([line]))
                    if len(row)<3 or row[0].strip() not in ('0','Background'):
                        continue
                    updated=list(row)
                    updated[2]=bg_names[str(safe_source(folder,row[2]))]
                    # Always quote the background name as osu! expects.
                    output_events[i]=','.join(updated[:2])+',"'+updated[2]+'"'+(','+','.join(updated[3:]) if len(updated)>3 else '')
                core.set_kv(general,'AudioFilename',audio_name)
                version=base_version+suffix
                preferred=version;number=2
                def map_filename(v):
                    return core.safe_name(f'Various Artists - {plain_title(pack_name)} ({creator}) [{v}]')+'.osu'
                while map_filename(version).casefold() in names:
                    version=f'{preferred} ({number})';number+=1
                filename=map_filename(version)
                if len(filename)>240:
                    raise ValueError('Pack/chart names are too long for the output filename. Shorten the pack name.')
                names.add(filename.casefold())
                for key,value in dict(Title=plain_title(pack_name),TitleUnicode=pack_name,Artist=artist,ArtistUnicode=artist_unicode,Creator=creator,Version=version,BeatmapID='0',BeatmapSetID='-1').items():
                    core.set_kv(metadata,key,value)
                if tags is not None:core.set_kv(metadata,'Tags',tags)
                for key,value in [('OverallDifficulty',format(od,'g')),('HPDrainRate',format(hp,'g'))]:core.set_kv(difficulty,key,value)
                text=header+'\r\n'+''.join('\r\n['+n+']\r\n'+'\r\n'.join(lines)+'\r\n' for n,lines in output_sections)
                (stage/filename).write_bytes(text.encode('utf-8'))
                completed+=1;report(completed/total,f'Prepared {title}{suffix}')
        # Exclusive directory creation prevents overwriting any existing pack.
        destination.mkdir()
        try:
            for file in stage.iterdir():shutil.copyfile(file,destination/file.name)
        except BaseException:
            shutil.rmtree(destination)
            raise
    report(1,f'Created {destination}')
    return str(destination),completed
