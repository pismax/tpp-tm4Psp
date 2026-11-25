"""Portable, read-only import and validated copy-on-export for TM4 PSP.

Container codecs are adapted from the user's tm4_translation research tools.
No model, translator, or external research workspace is needed at runtime.
"""
import sys, os, json, struct, hashlib, base64, re, pathlib, tempfile, shutil, csv, io, collections, zlib
from pidx import Pidx, Fsts, decompress_payload
from tsid2 import Tsid
from iso9660 import parse_iso, patch_iso
import rebuild

PACK_PREFIX='PSP_GAME/USRDIR/disc/pack/'
VERSION=1
JP=re.compile(r'[\u3000-\u30ff\u3400-\u9fff\uff00-\uffef]')
# Name/context selectors use two DECIMAL digits. Preserve their parameters,
# plus the lower-level renderer's style/timing/colour arguments.
TOKEN=re.compile(r'\\(?:[dghijkmp][0-9]{2}|s[0-9]{1,2}|v[0-9]{1,3}|c[0-9A-Fa-f]{8}|[A-Za-z](?:\[[^\]\r\n]*\])?)|%(?:\d+\$)?[-+ #0]*\d*(?:\.\d+)?[sdifuxXoc%]')
# Byte-oriented substitution layer plus the literal-newline wrapper. The
# renderer's v code is CP932-aware and does not create this trail-byte issue.
ESCAPE_PREFIXES='cdeghijkmnprsxz'
# char_char record IDs, not the separate decimal name-control selectors.
# Shared with the Node adapter so older staged projects receive the same roles.
SPEAKER_ROLES=json.loads((pathlib.Path(__file__).resolve().parent.parent/'speaker-roles.json').read_text(encoding='utf8'))

def speaker_metadata(char,names):
    role=SPEAKER_ROLES.get(str(char))
    return {'speakerId':char,**(role or ({'rowInfoText':names[char]} if char in names else {}))}

def digest(d):return hashlib.sha256(d).hexdigest()
def source_identity(p):
    h=hashlib.sha256();crc=0
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(4<<20),b''):h.update(b);crc=zlib.crc32(b,crc)
    return {'isoSha256':h.hexdigest(),'isoCrc32':f'{crc&0xffffffff:08X}'}
def full_hash(p):return source_identity(p)['isoSha256']
def save_json(p,obj):
    p=pathlib.Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(obj,ensure_ascii=False,separators=(',',':')),encoding='utf8')
def load_json(p):return json.loads(pathlib.Path(p).read_text(encoding='utf-8-sig'))
def safe(root,name):
    name=name.replace('\\','/');parts=name.split('/')
    if name.startswith('/') or any(p in ('..','') or ':' in p for p in parts):raise ValueError('Invalid resource path: '+name)
    target=pathlib.Path(root).resolve().joinpath(*parts)
    if not target.is_relative_to(pathlib.Path(root).resolve()):raise ValueError('Path escapes resource root')
    return target
def sjis(raw):return raw.decode('cp932',errors='strict')
def encode(text):
    # CP932's horizontal bar is 81 5C. Before English "hey", its trail byte
    # forms the game's raw-byte \h escape and substitutes a name. Use an ASCII
    # hyphen for the otherwise unencodable English em dash; keep drafts intact.
    return text.replace('\u2014','-').encode('cp932',errors='strict')
def normalized(text):return text.replace('\r\n','\n').replace('\r','\n')

def interface_image(name):
    name='/'+name.replace('\\','/')
    return '/interface/' in name and '/extra/gallery/' not in name

def validate(source,target,layout=None,policy=None):
    if '\0' in target:raise ValueError('Embedded NUL is not allowed')
    mode=lambda key:policy.get('rules',{}).get(key,'warn') if policy is not None else 'block'
    strict=(layout is None or layout.get('preserveLineCount',True)) and mode('lineCount')=='block'
    if strict and len(normalized(source).split('\n'))!=len(normalized(target).split('\n')):raise ValueError('Preserve source line count')
    if strict and source.count('\\n')!=target.count('\\n'):raise ValueError('Preserve literal \\n line breaks')
    if layout is not None:
        lines=re.split(r'\n|\\n',normalized(target))
        maximum=3 if layout.get('maxLines') is None else min(3,layout['maxLines'])
        if len(lines)>maximum:raise ValueError(f'Message box exceeds maximum {maximum} lines')
        if mode('lineWidth')=='block' and layout.get('maxCharsPerLine') is not None and any(len(line)>layout['maxCharsPerLine'] for line in lines):raise ValueError(f'Message box exceeds maximum {layout["maxCharsPerLine"]} stored characters per line')
    tokens=lambda text:collections.Counter(token for token in TOKEN.findall(text) if strict or token!='\\n')
    expected,actual=tokens(source),tokens(target)
    if mode('nameCodes')!='block':
        for token in set(expected)|set(actual):
            if re.fullmatch(r'\\h[0-9]{2}',token):
                if actual[token]>expected[token]:raise ValueError('Do not add or change a name/address selector')
                expected[token]=actual[token]
    if +expected!=+actual:raise ValueError('Preserve control codes and printf placeholders')
    functional=lambda text:[token for token in TOKEN.findall(text) if token!='\\n' and not (mode('nameCodes')!='block' and re.fullmatch(r'\\h[0-9]{2}',token))]
    if functional(source)!=functional(target):raise ValueError('Preserve the required order of functional controls and printf arguments')
    raw=encode(target)
    # The game scans these escapes without excluding CP932 trail bytes.
    # Reject accidental escapes from encodable characters such as ― and ソ;
    # intentionally authored backslash control codes remain valid above.
    for index,char in enumerate(target[:-1]):
        if target[index+1] not in ESCAPE_PREFIXES:continue
        encoded=encode(char)
        if len(encoded)==2 and encoded[-1]==0x5c:
            raise ValueError(f'CP932 trail-byte escape collision before {target[index+1]!r}; replace {char!r} with an ASCII hyphen or separate it from the following letter')
    return raw

def iso_inventory(iso):
    entries=parse_iso(iso);by={f.path.split(';')[0]:f for f in entries if not f.is_dir}
    required=[PACK_PREFIX+'tokimeki.dat',PACK_PREFIX+'tokimeki.idx','UMD_DATA.BIN']
    if any(p not in by for p in required):raise ValueError('Not a supported Tokimeki Memorial 4 PSP ISO')
    with open(iso,'rb') as f:
        serial=by['UMD_DATA.BIN'];f.seek(serial.lba*2048);disc=f.read(serial.size)
    if not any(code in disc for code in (b'ULJM-05541',b'NPJH-50127',b'NPJH50127')):raise ValueError('Unsupported disc serial: '+repr(disc[:32]))
    return by

def read_packs(iso,directory=None):
    entries=iso_inventory(iso);packs={}
    with open(iso,'rb') as f:
        for name,entry in entries.items():
            if not name.startswith(PACK_PREFIX) or not name.endswith(('.dat','.idx')) or name.endswith('/voice.dat'):continue
            f.seek(entry.lba*2048);data=f.read(entry.size)
            if len(data)!=entry.size:raise ValueError('Truncated ISO pack: '+name)
            short=name[len(PACK_PREFIX):];packs[short]=data
            if directory:
                p=safe(directory,short);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    return packs

def resources(packs, include_fonts=False):
    idx=Pidx(packs['tokimeki.idx']);dat=packs['tokimeki.dat']
    # Interface textures are duplicated in the main archive. Match their
    # filenames before decompressing main-archive graphics; backgrounds and
    # portraits are huge and have no lettering to translate.
    interface_names=set()
    for name,data in packs.items():
        if name in ('tokimeki.dat','tokimeki.idx') or data[:4]!=b'PIDX':continue
        for entry in Pidx(data).entries:
            if entry.is_folder:continue
            if data[entry.offset:entry.offset+4]==b'FSTS':
                for item in Fsts(data,entry.offset).entries:
                    if item.name and interface_image(item.name):
                        interface_names.add(item.name.replace('\\','/').split('/')[-1])
    for i,e in enumerate(idx.entries):
        if e.is_folder or not e.name or (e.pack and 'voice.dat' in e.pack):continue
        if pathlib.Path(e.name).suffix.lower() not in ('.dat','.asb','.csv','.gim','.png') + (('.fnt',) if include_fonts else ()):continue
        if pathlib.Path(e.name).suffix.lower()=='.gim' and e.name.split('/')[-1] not in interface_names:continue
        raw=decompress_payload(dat,e.offset,e.size,e.zsize)
        if len(raw)!=e.size:raise ValueError('Decompressed length mismatch: '+e.name)
        yield f'tokimeki/{i:05d}_{e.name}',raw
    for name,data in sorted(packs.items()):
        if name in ('tokimeki.dat','tokimeki.idx') or data[:4]!=b'PIDX':continue
        archive=Pidx(data)
        for e in archive.entries:
            if e.is_folder:continue
            blob=decompress_payload(data,e.offset,e.size,e.zsize)
            if blob[:4]==b'FSTS':
                inner=Fsts(blob)
                for item in inner.entries:
                    if not item.name:raise ValueError('Unnamed FSTS member')
                    ext=pathlib.Path(item.name).suffix.lower()
                    if ext not in ('.dat','.asb','.csv','.gim','.png') + (('.fnt',) if include_fonts else ()):continue
                    if ext in ('.gim','.png') and not interface_image(item.name):continue
                    raw=decompress_payload(blob,item.offset,item.size,item.zsize)
                    if len(raw)!=item.size:raise ValueError('Decompressed length mismatch: '+item.name)
                    yield 'packs/'+name+'/'+item.name.replace('\\','/'),raw
            else:
                yield 'packs/'+name+'/'+(e.name or 'entry'),blob

def asb_strings(data):
    if not data:return []
    if len(data)<64:raise ValueError('Truncated ASB header')
    start=struct.unpack_from('<I',data,0x34)[0]
    if start<64 or start>len(data):raise ValueError('Invalid ASB string table offset')
    pos=start;result=[]
    while pos<len(data):
        end=data.find(b'\0',pos)
        if end<0:raise ValueError('Unterminated ASB string')
        if end>pos:result.append((pos-start,data[pos:end]))
        pos=end+1
    return result

def reference_map(data):
    start=struct.unpack_from('<I',data,0x34)[0];found=collections.defaultdict(list)
    for pos in range(64,start-3):found[struct.unpack_from('<I',data,pos)[0]].append(pos)
    return found
def simple_ref(data,pos):
    return pos>=2 and data[pos-2:pos] in (b'\x01\x01',b'\x05\x01') and data[pos+4:pos+9]==b'\x29\0\0\0\0'

def speaker_names(groups):
    names={}
    for g in groups.values():
        name=g['paths'][0].split('/')[-1];match=re.search(r'(girl_([a-l])_name|mate_([mn])_name)\.dat$',name)
        if not match or g['raw'][:4]!=b'TSID':continue
        t=Tsid.parse(g['raw']);values=[sjis(v) for entry,rec in zip(t.names,t.tsdd.records if t.tsdd else []) if entry==b'fullname' for tc,v in rec.fields if tc==9 and JP.search(sjis(v))]
        if values:
            key=ord(match[2])-97 if match[2] else 12+ord(match[3])-ord('m')
            names[key]=values[0]
    return names

def asb_speaker(data,ref,names):
    # Direct call 0x13 immediately before display function 0. Arguments use
    # opcode 01 (integer) or 05 (string), with 1..5 immediate parameters.
    # Only report a single static character ID; dynamic expressions stay blank.
    end=ref-2
    if data[end-5:end]!=b'\x29\x13\0\0\0':return {}
    args_end=end-5;args=[];pos=args_end
    for _ in range(5):
        if pos<5 or data[pos-5]!=1:break
        args.insert(0,struct.unpack_from('<i',data,pos-4)[0]);pos-=5
    # Variable argument lists have a leading 01 <count> marker. A one-arg
    # call is exactly 01 01 <character> 29 13... .
    if len(args)==1 and data[pos-1:pos]==b'\x01':char=args[0]
    elif len(args)==5:char=args[0]
    else:return {}
    return {**speaker_metadata(char,names),'speakerEvidence':'ASB immediate message setup call 0x13'}

def csv_cells(text):
    # Token spans preserve exact CRCRLF line endings, comments and quoting.
    result=[];pos=0;row=0;col=0
    while pos<len(text):
        start=pos
        if text[pos]=='"':
            pos+=1
            while pos<len(text):
                if text[pos]=='"':
                    if pos+1<len(text) and text[pos+1]=='"':pos+=2;continue
                    pos+=1;break
                pos+=1
            else:raise ValueError('Unterminated CSV quote')
            raw=text[start:pos];value=raw[1:-1].replace('""','"')
        else:
            while pos<len(text) and text[pos] not in ',\r\n':pos+=1
            raw=text[start:pos];value=raw
        result.append((row,col,start,pos,value,raw.startswith('"')))
        if pos>=len(text):break
        if text[pos]==',':col+=1;pos+=1
        else:
            if text[pos:pos+3]=='\r\r\n':pos+=3
            elif text[pos:pos+2]=='\r\n':pos+=2
            else:pos+=1
            row+=1;col=0
    return result

def extract_rows(kind,data,names=None):
    rows=[];names=names or {}
    def add(text,context,**meta):
        if JP.search(text):rows.append({'text':text,'context':context,**meta})
    if kind=='TSID':
        t=Tsid.parse(data)
        fields=[sjis(x) for x in t.tstt]
        for ri,rec in enumerate(t.tsdd.records if t.tsdd else []):
            speaker={}
            for fi,(tc,val) in enumerate(rec.fields):
                if fields[fi].lower() in ('char','speaker','chara'):
                    char=sjis(val) if tc==9 else int.from_bytes(val,'little',signed=tc in (1,2,3))
                    if isinstance(char,int):speaker=speaker_metadata(char,names)
                    elif JP.search(char):speaker={'rowInfoText':char}
            for fi,(tc,val) in enumerate(rec.fields):
                if tc==9:
                    text=sjis(val);field=fields[fi] if fi<len(fields) else str(fi)
                    entry=sjis(t.names[ri]) if ri<len(t.names) else str(ri)
                    add(text,f'record/{ri}/{entry}/{field}/{fi}',rec=ri,slot=fi,field=field,entry=entry,byteLength=len(val),**speaker)
    elif kind=='ASB':
        refs=reference_map(data)
        for rel,raw in asb_strings(data):
            text=sjis(raw)
            if not JP.search(text):continue
            occurrences=refs.get(rel,[]);simple=bool(occurrences) and all(simple_ref(data,p) for p in occurrences)
            speakers=[asb_speaker(data,p,names) for p in occurrences if simple_ref(data,p)]
            ids={s.get('speakerId') for s in speakers}
            speaker=speakers[0] if speakers and len(ids)==1 else {}
            add(text,f'string/{rel}',rel=rel,byteLength=len(raw),canGrow=simple,
                messageType='messageBox' if simple else 'unknown',
                messageTypeEvidence='All references are direct display function 0 operands' if simple else 'Unclassified or mixed ASB references',**speaker)
    elif kind=='CSV':
        for row,col,start,end,value,quoted in csv_cells(sjis(data)):
            add(value,f'cell/{row}/{col}',csvRow=row,csvCol=col,start=start,end=end,quoted=quoted,byteLength=len(encode(value)))
    return rows

def descriptor(kind,raw,paths,names=None):
    return {'version':VERSION,'kind':kind,'sha256':digest(raw),'raw':base64.b64encode(raw).decode('ascii'),
            'destinations':paths,'rows':extract_rows(kind,raw,names)}

def scan(request):
    iso=request['iso'];out=pathlib.Path(request['out']);out.mkdir(parents=True,exist_ok=True)
    packs=read_packs(iso);groups={};stats=collections.Counter();image_errors=[]
    for name,raw in resources(packs):
        h=digest(raw)
        if h not in groups:groups[h]={'raw':raw,'paths':[]}
        groups[h]['paths'].append(name);stats['extractedFiles']+=1
        if stats['extractedFiles']%200==0:save_json(out/'progress.json',{'phase':'extract','files':stats['extractedFiles'],'resource':name})
    names=speaker_names(groups);files=[];images=[]
    for h,g in groups.items():
        raw=g['raw'];paths=g['paths'];kind='TSID' if raw[:4]==b'TSID' else 'ASB' if any(p.endswith('.asb') for p in paths) else 'CSV' if any(p.endswith('.csv') for p in paths) else None
        # Facial-animation CSVs hold developer labels and numeric controls;
        # they are not player-facing strings.
        if kind=='CSV' and any(p.endswith('/faceparam.csv') for p in paths):continue
        if kind and raw:
            obj=descriptor(kind,raw,paths,names)
            if obj['rows']:
                stem=paths[0].split('/')[-1];file=f'text/{kind}/{stem}.{h[:12]}.tm4.json'
                save_json(out/file,obj);files.append(file);stats[kind+'Rows']+=len(obj['rows']);stats['speakerRows']+=sum(bool(r.get('rowInfoText')) for r in obj['rows'])
        if request.get('includeImages') and (raw[:12]==b'MIG.00.1PSP\0' or raw[:8]==b'\x89PNG\r\n\x1a\n'):
            if not any(interface_image(p) for p in paths):continue
            try:
                import tm4_images
                if raw[:8]==b'\x89PNG\r\n\x1a\n':
                    from PIL import Image
                    im=Image.open(io.BytesIO(raw)).convert('RGBA');png=raw;w,hh=im.size;pix=digest(im.tobytes());ikind='PNG'
                else:png,w,hh,pix=tm4_images.png_bytes(raw);ikind='GIM'
                file=f'images/{h[:16]}_{pathlib.Path(paths[0]).stem}.png';p=out/file;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(png)
                image={'file':file,'kind':ikind,'width':w,'height':hh,'sha256':h,'pixelSha256':pix,'destinations':paths,'label':next((p for p in paths if p.startswith('packs/')),paths[0])}
                save_json(out/(file+'.tm4.json'),{'version':VERSION,'kind':ikind,'raw':base64.b64encode(raw).decode('ascii'),'sha256':h,'destinations':paths,'rows':[]})
                images.append(image)
            except (ValueError,ImportError,IndexError,struct.error) as ex:image_errors.append({'resource':paths[0],'error':str(ex)})
        if (len(files)+len(images))%50==0:save_json(out/'progress.json',{'phase':'parse','textFiles':len(files),'images':len(images)})
    if not files:raise ValueError('No translatable TM4 resources found')
    manifest={'version':VERSION,'iso':str(pathlib.Path(iso).resolve()),**source_identity(iso),'isoSize':os.path.getsize(iso),'files':files,'images':images,'speakerNames':names,'stats':dict(stats),'imageErrors':image_errors}
    save_json(out/'manifest.json',manifest)
    return {'sourceDir':str(out.resolve()),'files':files,'manifest':manifest}

def rebuild_resource(obj,translations,message_layout=None,validation_policy=None):
    data=base64.b64decode(obj['raw']);kind=obj['kind'];changes=[];errors=[]
    if digest(data)!=obj['sha256']:raise ValueError('Staged resource checksum mismatch')
    refs=reference_map(data) if kind=='ASB' else {}
    for i,row in enumerate(obj['rows']):
        value=translations.get(row['context'])
        if value is None or value=='' or value==row['text']:continue
        uses=refs.get(row.get('rel'),[])
        layout=(message_layout if message_layout is not None else {'preserveLineCount':False,'maxLines':3,'maxCharsPerLine':44}) if uses and all(simple_ref(data,pos) for pos in uses) else None
        try:changes.append((row,validate(row['text'],value,layout,validation_policy)))
        except (ValueError,UnicodeError) as ex:errors.append(f'row {i+1} ({row["context"]}): {ex}')
    if errors:raise ValueError('\n'.join(errors))
    if not changes:return data
    if kind=='TSID':
        t=Tsid.parse(data)
        for row,raw in changes:t.tsdd.records[row['rec']].fields[row['slot']]=(9,raw)
        return t.encode()+t.trailing
    if kind=='ASB':
        out=bytearray(data);start=struct.unpack_from('<I',data,0x34)[0]
        for row,raw in changes:
            rel=row['rel'];budget=row['byteLength']
            if len(raw)<=budget:out[start+rel:start+rel+budget]=raw+b'\0'*(budget-len(raw))
            elif refs.get(rel) and all(simple_ref(data,p) for p in refs[rel]):
                new_rel=len(out)-start;out+=raw+b'\0'
                for pos in refs[rel]:struct.pack_into('<I',out,pos,new_rel)
            else:errors.append(f'{row["context"]}: {len(raw)} CP932 bytes exceed fixed budget {budget}; shorten by {len(raw)-budget} bytes')
        if errors:raise ValueError('\n'.join(errors))
        if len(out)!=len(data):
            struct.pack_into('<I',out,0x38,len(out)-start);struct.pack_into('<I',out,0x3c,len(out))
        return bytes(out)
    if kind=='CSV':
        text=sjis(data)
        for row,raw in sorted(changes,key=lambda c:c[0]['start'],reverse=True):
            value=sjis(raw)
            if row['quoted'] or any(c in value for c in ',"\r\n'):value='"'+value.replace('"','""')+'"'
            text=text[:row['start']]+value+text[row['end']:]
        return encode(text)
    raise ValueError('Unsupported resource kind '+kind)

def build(request):
    iso=request['iso'];target=pathlib.Path(request['target']);manifest=request['manifest'];stage=pathlib.Path(request['stage'])
    if pathlib.Path(iso).resolve()==target.resolve():raise ValueError('Cannot overwrite source ISO')
    if target.exists():raise ValueError('Output already exists: '+str(target))
    if full_hash(iso)!=manifest['isoSha256']:raise ValueError('Source ISO differs from the imported disc')
    modified={};errors=[];stats=collections.Counter();replacement={};font_report=None;original_packs=None
    weight=request.get('halfWidthWeight','regular')
    if weight not in ('regular','bold'):raise ValueError('Unsupported half-width font weight: '+str(weight))
    if weight=='bold' and not request.get('halfWidthEboot'):raise ValueError('Bold Latin text requires half-width alphabet support to be enabled')
    if request.get('halfWidthEboot'):
        import tm4_font
        executable=pathlib.Path(request['halfWidthEboot']).read_bytes()
        font_report=tm4_font.inspect(executable)
        replacement['PSP_GAME/SYSDIR/EBOOT.BIN']=tm4_font.patch(executable)
        font_report['weight']=weight
        if weight=='bold':
            original_packs=read_packs(iso)
            destinations=[]
            for name,raw in resources(original_packs,include_fonts=True):
                if name.split('/')[-1].endswith('tm4_font16.fnt'):
                    modified[name],atlas_report=tm4_font.bold_atlas(raw,executable)
                    destinations.append(name)
            if not destinations:raise ValueError('Original TM4 font atlas was not found in the source ISO')
            font_report['atlas']={**atlas_report,'destinations':destinations}
            stats['fontResources']=len(destinations)
    # Validate the entire selection before writing an ISO.
    for name,translations in request.get('translations',{}).items():
        if name not in manifest['files']:raise ValueError('Unknown staged resource: '+name)
        obj=load_json(safe(stage,name))
        try:raw=rebuild_resource(obj,translations,request.get('messageBoxLayout'),request.get('validationPolicy'))
        except (ValueError,UnicodeError) as ex:errors.append(name+': '+str(ex));continue
        if digest(raw)!=obj['sha256']:
            for dest in obj['destinations']:modified[dest]=raw
            stats['textResources']+=1
    for name,png_path in request.get('images',{}).items():
        image=next((im for im in manifest.get('images',[]) if im['file']==name),None)
        if image is None:raise ValueError('Unknown image resource: '+name)
        obj=load_json(safe(stage,name+'.tm4.json'));original=base64.b64decode(obj['raw'])
        if digest(original)!=obj['sha256']:raise ValueError('Staged image checksum mismatch')
        try:
            png=pathlib.Path(png_path).read_bytes()
            if image['kind']=='GIM':
                import tm4_images
                raw=tm4_images.replace(original,png)
            else:
                from PIL import Image
                im=Image.open(io.BytesIO(png))
                if im.size!=(image['width'],image['height']):raise ValueError('Keep original image dimensions')
                raw=png
            if raw!=original:
                for dest in obj['destinations']:modified[dest]=raw
                stats['imageResources']+=1
        except (ValueError,OSError) as ex:errors.append(name+': '+str(ex))
    if errors:raise ValueError('Correct these translations before export:\n'+'\n'.join(errors))
    target.parent.mkdir(parents=True,exist_ok=True)
    # Reserve output exclusively. The ISO writer operates on a private temporary
    # file; no partially patched ISO is presented as a completed export.
    with tempfile.TemporaryDirectory(prefix='tpp-tm4-build-') as work:
        work=pathlib.Path(work);packdir=work/'original';mods=work/'modified';out=work/'rebuilt';out.mkdir()
        if modified:
            read_packs(iso,packdir)
            for dest,raw in modified.items():
                p=safe(mods,dest);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
            rebuild.rebuild_pack_files(str(packdir),str(mods),str(out))
            if any(name.startswith('tokimeki/') for name in modified):rebuild.rebuild_tokimeki(str(packdir/'tokimeki.dat'),str(packdir/'tokimeki.idx'),str(mods),str(out))
            replacement.update({PACK_PREFIX+p.name:p.read_bytes() for p in out.iterdir()})
            # Re-extract the rebuilt archive set and compare every changed member.
            packs=original_packs if original_packs is not None else read_packs(iso)
            for p in out.iterdir():packs[p.name]=p.read_bytes()
            pending=set(modified)
            for name,raw in resources(packs,include_fonts=weight=='bold'):
                if name in pending:
                    if raw!=modified[name]:raise ValueError('Rebuilt resource verification failed: '+name)
                    pending.remove(name)
            if pending:raise ValueError('Resources missing from rebuilt packs: '+repr(sorted(pending)))
        if replacement:
            tmp=work/'patched.iso';patch_iso(iso,tmp,replacement)
            if font_report:
                entry=next(e for e in parse_iso(tmp) if e.path=='PSP_GAME/SYSDIR/EBOOT.BIN')
                with open(tmp,'rb') as stream:
                    stream.seek(entry.lba*2048);actual=stream.read(entry.size)
                if actual!=replacement[entry.path]:raise ValueError('Patched executable verification failed')
        else:tmp=pathlib.Path(iso)
        # Copy with exclusive creation also protects against a name collision
        # occurring while validation/rebuilding ran.
        with open(tmp,'rb') as src,open(target,'xb') as dst:shutil.copyfileobj(src,dst,4<<20)
    report={'path':str(target.resolve()),'changedMembers':len(modified),'stats':dict(stats),'isoSize':target.stat().st_size,'halfWidthFont':font_report,'sourceChecksum':request.get('sourceChecksum')}
    save_json(str(target)+'.report.json',report)
    return report

def main():
    command=sys.argv[1];request=load_json(sys.argv[2])
    if command=='scan':result=scan(request)
    elif command=='build':result=build(request)
    elif command=='font':
        import tm4_font
        result=tm4_font.inspect(pathlib.Path(request['source']).read_bytes())
    elif command=='detect':
        try:iso_inventory(request['iso']);result=True
        except (ValueError,OSError,IndexError,struct.error):result=False
    elif command=='write':
        obj=load_json(request['source']);raw=rebuild_resource(obj,request.get('translations',{}),request.get('messageBoxLayout'),request.get('validationPolicy'));p=pathlib.Path(request['target']);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw);result=str(p)
    else:raise ValueError('Unknown bridge command '+command)
    save_json(sys.argv[3],{'result':result})

if __name__=='__main__':
    try:main()
    except Exception as ex:
        import traceback
        save_json(sys.argv[3],{'error':str(ex),'stack':traceback.format_exc()});sys.exit(1)
