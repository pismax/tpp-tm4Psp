"""TM4 single-frame PSP GIM codec. Preserve layout/palettes; edit pixels only.

GIM block layout cross-checked with vn-tools/arc_unpacker's GIM decoder:
https://github.com/vn-tools/arc_unpacker/blob/master/src/dec/playstation/gim_image_decoder.cc
"""
import struct, io, hashlib

def u16(d, p): return struct.unpack_from('<H', d, p)[0]
def u32(d, p): return struct.unpack_from('<I', d, p)[0]

def layout(data):
    if data[:12] != b'MIG.00.1PSP\0': raise ValueError('Not a PSP GIM')
    pos=0x30; chunks={}
    while pos+16<=len(data):
        kind=u16(data,pos); size=u32(data,pos+4); next_=u32(data,pos+8)
        if size<16 or pos+size>len(data): raise ValueError('Invalid GIM block size')
        if kind in (4,5):
            if kind in chunks: raise ValueError('Multiple GIM frames are unsupported')
            h=pos+u32(data,pos+12)
            fmt=u16(data,h+4); order=u16(data,h+6)
            width=u16(data,h+8);height=u16(data,h+10);bpp=u16(data,h+12)
            start=h+u32(data,h+28); end=h+u32(data,h+32)
            if fmt>5 or order>1 or not width or not height or start< h+48 or end>pos+size or end<start:
                raise ValueError('Unsupported GIM format/layout')
            # One level and frame only. TM4's palette/image blocks use these.
            if u16(data,h+42)!=1 or u16(data,h+46)!=1: raise ValueError('GIM mipmaps/multiple frames unsupported')
            chunks[kind]={'format':fmt,'order':order,'width':width,'height':height,'bpp':bpp,'start':start,'end':end,
                          'pitchAlign':u16(data,h+14)}
        if not next_ or next_<16: break
        pos+=next_
    if 4 not in chunks: raise ValueError('No GIM image block')
    return chunks

def color(raw, fmt):
    if fmt==3: return tuple(raw)
    v=int.from_bytes(raw,'little')
    if fmt==0: return ((v&31)*255//31,((v>>5)&63)*255//63,((v>>11)&31)*255//31,255)
    if fmt==1: return ((v&31)*255//31,((v>>5)&31)*255//31,((v>>10)&31)*255//31,255 if v&0x8000 else 0)
    if fmt==2: return ((v&15)*17,((v>>4)&15)*17,((v>>8)&15)*17,((v>>12)&15)*17)
    raise ValueError('Unsupported GIM palette format')

def pack_color(c,fmt):
    r,g,b,a=c
    if fmt==3:return bytes(c)
    if fmt==0:v=(r*31//255)|((g*63//255)<<5)|((b*31//255)<<11)
    elif fmt==1:v=(r*31//255)|((g*31//255)<<5)|((b*31//255)<<10)|((1 if a>=128 else 0)<<15)
    elif fmt==2:v=(round(r/17))|(round(g/17)<<4)|(round(b/17)<<8)|(round(a/17)<<12)
    else:raise ValueError('Unsupported GIM color format')
    return v.to_bytes(2,'little')

def pixel_offset(info,x,y):
    bits=info['bpp']; row_bytes=(info['width']*bits+7)//8
    align=max(1,info['pitchAlign']); stride=(row_bytes+align-1)//align*align
    byte_x=x*bits//8
    if info['order']:
        stride=(stride+15)//16*16
        off=((y//8)*(stride//16)+byte_x//16)*128+(y%8)*16+byte_x%16
    else:off=y*stride+byte_x
    off+=info['start']
    if off+(bits+7)//8>info['end']:raise ValueError('GIM pixel overrun')
    return off

def decode(data):
    from PIL import Image
    chunks=layout(data); im=chunks[4]; fmt=im['format']; palette=[]
    if fmt>=4:
        pal=chunks.get(5)
        if not pal or pal['format']>3:raise ValueError('Missing GIM palette')
        step=4 if pal['format']==3 else 2
        palette=[color(data[p:p+step],pal['format']) for p in range(pal['start'],pal['start']+pal['width']*step,step)]
    rgba=bytearray()
    for y in range(im['height']):
        for x in range(im['width']):
            p=pixel_offset(im,x,y)
            if fmt==4:idx=(data[p]>>(4*(x%2)))&15
            elif fmt==5:idx=data[p]
            else:idx=None
            rgba.extend(palette[idx] if idx is not None else color(data[p:p+(4 if fmt==3 else 2)],fmt))
    image=Image.frombytes('RGBA',(im['width'],im['height']),bytes(rgba))
    return image, chunks

def png_bytes(data):
    image,_=decode(data);out=io.BytesIO();image.save(out,format='PNG')
    return out.getvalue(),image.width,image.height,hashlib.sha256(image.tobytes()).hexdigest()

def replace(data,png):
    from PIL import Image
    original,chunks=decode(data);image=Image.open(io.BytesIO(png)).convert('RGBA');im=chunks[4];fmt=im['format']
    if image.size!=original.size:raise ValueError('Keep image dimensions %s x %s'%original.size)
    if image.tobytes()==original.tobytes():return data
    palette=[]
    if fmt>=4:
        pal=chunks[5];step=4 if pal['format']==3 else 2
        palette=[color(data[p:p+step],pal['format']) for p in range(pal['start'],pal['start']+pal['width']*step,step)]
    # Keep the existing CLUT: untouched pixels and shared palette meaning stay
    # exact. Changed artwork is mapped to its nearest original RGBA entry.
    cache={};out=bytearray(data);pixels=image.load();old=original.load()
    for y in range(image.height):
        for x in range(image.width):
            c=pixels[x,y]
            if c==old[x,y]:continue
            p=pixel_offset(im,x,y)
            if fmt>=4:
                if c not in cache:
                    cache[c]=min(range(min(len(palette),16 if fmt==4 else 256)),key=lambda i:sum((c[j]-palette[i][j])**2*(2 if j==3 else 1) for j in range(4)))
                idx=cache[c]
                if fmt==4:
                    shift=4*(x%2);out[p]=(out[p]&~(15<<shift))|(idx<<shift)
                else:out[p]=idx
            else:
                b=pack_color(c,fmt);out[p:p+len(b)]=b
    return bytes(out)
