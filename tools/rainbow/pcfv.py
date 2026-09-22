"""PCFV0001 sector container shared by authoring, repair and inspection tools."""
import struct
import zlib
from pathlib import Path

SECTOR = 2048
MAX_FRAMES = 4096
MAX_FRAME_SECTORS = 4
HEADER = struct.Struct('<8s6H11I')
ENTRY = struct.Struct('<8I')


def sectors(n):
    return (n + SECTOR - 1) // SECTOR


def read(path):
    data = Path(path).read_bytes()
    if len(data) < HEADER.size:
        raise ValueError('truncated PCFV header')
    h = HEADER.unpack_from(data)
    magic, w, hgt, fpsn, fpsd, count, flags, index_bytes, start, stride, audio_bytes, audio_sectors, preroll, refill, ring, rate, r0, r1 = h
    if magic != b'PCFV0001' or (w, hgt) != (256, 240):
        raise ValueError('expected PCFV0001, 256x240')
    if not 1 <= count <= MAX_FRAMES or not fpsn or not fpsd or fpsn > 60 * fpsd:
        raise ValueError('invalid frame count or frame rate')
    if index_bytes != count * ENTRY.size or start < sectors(HEADER.size + index_bytes):
        raise ValueError('invalid PCFV index/data start')
    if not 1 <= stride <= MAX_FRAME_SECTORS or len(data) % SECTOR:
        raise ValueError('invalid video slot stride or file sector alignment')
    if len(data) < start * SECTOR or audio_sectors != sectors(audio_bytes):
        raise ValueError('truncated index or inconsistent audio length')
    if flags not in (0, 2) or (audio_bytes and flags != 2):
        raise ValueError('this tool supports silent PCFV and interleaved MP2, not ADPCM')
    frames, audio_parts, intervals = [], [], []
    for i in range(count):
        vs, size, ns, crc, aus, ans, abo, ef = ENTRY.unpack_from(data, HEADER.size + i * ENTRY.size)
        if not 1 <= ns <= stride or not 0 < size <= ns * SECTOR or vs < start:
            raise ValueError(f'frame {i}: invalid video extent')
        if (vs + ns) * SECTOR > len(data):
            raise ValueError(f'frame {i}: truncated video sectors')
        frame = data[vs * SECTOR:vs * SECTOR + size]
        if zlib.crc32(frame) != crc:
            raise ValueError(f'frame {i}: video CRC mismatch')
        frames.append(frame)
        intervals.append((vs, vs + ns))
        if ans:
            if not audio_bytes or ans > 4 or aus < start or (aus + ans) * SECTOR > len(data) or abo >= audio_bytes:
                raise ValueError(f'frame {i}: invalid MP2 chunk extent')
            audio_parts.append((abo, data[aus * SECTOR:(aus + ans) * SECTOR]))
            intervals.append((aus, aus + ans))
    intervals.sort()
    if any(a[1] > b[0] for a, b in zip(intervals, intervals[1:])):
        raise ValueError('overlapping PCFV extents')
    audio = bytearray()
    for offset, part in sorted(audio_parts):
        if offset != len(audio):
            raise ValueError('missing or overlapping MP2 bytes')
        audio.extend(part[:audio_bytes - offset])
    if len(audio) != audio_bytes:
        raise ValueError('incomplete MP2 stream')
    if audio and (rate != 16000 or preroll or ring or refill > 4):
        raise ValueError('unsupported MP2 layout')
    return dict(frames=frames, fps_num=fpsn, fps_den=fpsd, audio=bytes(audio), stride=stride)


def check_mp2(audio):
    """Only the player's MPEG-2 Layer-II, 16 kHz, 32 kbit/s mono contract."""
    pos = count = 0
    while pos < len(audio):
        if pos + 4 > len(audio):
            raise ValueError('truncated MP2 header')
        word = int.from_bytes(audio[pos:pos + 4], 'big')
        if ((word >> 21) != 0x7ff or (word >> 19) & 3 != 2 or
                (word >> 17) & 3 != 2 or (word >> 12) & 15 != 4 or
                (word >> 10) & 3 != 2 or (word >> 6) & 3 != 3):
            raise ValueError('MP2 must be MPEG-2 Layer II, mono, 16000 Hz, 32 kbit/s')
        pos += 288 + ((word >> 9) & 1)
        count += 1
    if pos != len(audio) or not count:
        raise ValueError('empty or truncated MP2 frame')
    return count * 1152


def write(path, frames, fps_num=15, fps_den=1, audio=b'', lead_sectors=4, chunk_sectors=4):
    if not 1 <= len(frames) <= MAX_FRAMES or not 1 <= fps_num <= 65535 or not 1 <= fps_den <= 65535 or fps_num > 60 * fps_den:
        raise ValueError('unsupported frame count/rate')
    if not 1 <= lead_sectors <= 4 or not 1 <= chunk_sectors <= 4:
        raise ValueError('MP2 chunks must be 1..4 sectors')
    stride = max(sectors(len(f)) for f in frames)
    if not 1 <= stride <= MAX_FRAME_SECTORS or any(not f for f in frames):
        raise ValueError('frame exceeds the player\'s four-sector KRAM slot; re-encode from source')
    if audio:
        samples = check_mp2(audio)
        expected = len(frames) * fps_den * 16000 // fps_num
        if abs(samples - expected) > 2304:
            raise ValueError('MP2/video durations differ by more than two MP2 frames; trim/re-encode audio')
    start = sectors(HEADER.size + len(frames) * ENTRY.size)
    cursor, audio_pos = start, 0
    entries, payload = [], bytearray()
    for i, frame in enumerate(frames):
        vs = cursor
        payload.extend(frame)
        payload.extend(bytes(stride * SECTOR - len(frame)))
        cursor += stride
        aus = ans = abo = 0
        due = min(len(audio), (i + 1) * fps_den * 4000 // fps_num + lead_sectors * SECTOR)
        if audio_pos < due:
            limit = lead_sectors if i == 0 else chunk_sectors
            available = sectors(len(audio) - audio_pos)
            if i == 0 or due - audio_pos >= limit * SECTOR or due == len(audio):
                ans = min(limit, available)
                aus, abo = cursor, audio_pos
                part = audio[audio_pos:audio_pos + ans * SECTOR]
                payload.extend(part)
                payload.extend(bytes(ans * SECTOR - len(part)))
                audio_pos += len(part)
                cursor += ans
        entries.append(ENTRY.pack(vs, len(frame), stride, zlib.crc32(frame), aus, ans, abo, 0))
    if audio_pos != len(audio):
        raise ValueError('too few video entries for the audio chunks; split or trim the clip')
    header = HEADER.pack(b'PCFV0001', 256, 240, fps_num, fps_den, len(frames), 2 if audio else 0,
                         len(frames) * ENTRY.size, start, stride, len(audio), sectors(len(audio)),
                         0, chunk_sectors if audio else 0, 0, 16000 if audio else 0, 0, 0)
    with Path(path).open('wb') as out:
        out.write(header)
        out.write(b''.join(entries))
        out.write(bytes(start * SECTOR - HEADER.size - len(frames) * ENTRY.size))
        out.write(payload)
    return dict(frames=len(frames), slot_sectors=stride, total_sectors=cursor,
                audio_bytes=len(audio), payload_bytes=sum(map(len, frames)))
