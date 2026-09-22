/*
    pcfxtools -- a set of tools for NEC PC-FX development and reverse-engineering
    pcfx-cdlink; .cue and .bin generator.

Copyright (C) 2011        Alex Marshall "trap15" <trap15@raidenii.net>
Copyright (C) 2007        Ryphecha / Mednafen
Additional append/lbaheader support for non-RAM CD assets, 2026.
Additional cddaheader/cddadir support for Red Book audio tracks, 2026.

# This code is licensed to you under the terms of the MIT license;
# see file LICENSE or http://www.opensource.org/licenses/mit-license.php
*/

#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <string.h>
#include <ctype.h>

#ifndef _WIN32
#include <dirent.h>
#endif

#ifdef _WIN32
#include <winsock2.h>
#else
#include <arpa/inet.h>
#endif

#define SECTOR_SIZE 2048u
#define BOOT_SECTORS 2u
#define MIN_DISC_SECTORS (75u * 4u)
#define MAX_APPEND_FILES 256
/* Real (embedded-bytes) pregap at the audio-track1 -> data-track2 boundary,
   and again at the data-track2 -> first-CDDA-track3 boundary, matching every
   retail/PC-FXGA disc surveyed (Team Innocent, N-nyuu, Same Game FX): 2
   seconds, INDEX 00/01 within the SAME file, not a synthesized PREGAP line. */
#define DATA_PREGAP_SECTORS 150u

uint32_t le32(uint32_t i)
{
    i = ntohl(i);
    i = ((i & 0xFF000000) >> 24) |
        ((i & 0x00FF0000) >>  8) |
        ((i & 0x0000FF00) <<  8) |
        ((i & 0x000000FF) << 24);
    return i;
}

uint16_t le16(uint16_t i)
{
    i = ntohs(i);
    i = ((i & 0xFF00) >> 8) |
        ((i & 0x00FF) << 8);
    return i;
}

struct {
    char        header[0x10];
    char        unk[0x7F0];
    char        title[0x20];
    uint32_t    sect_off;
    uint32_t    sect_count;
    uint32_t    prog_off;
    uint32_t    prog_point;
    char        maker_id[4];
    char        maker_name[60];
    uint32_t    volume_no;
    uint16_t    version;
    uint16_t    country;
    char        date[8];
    char        pad[0x380];
    char        udata[0x400];
} __attribute__((packed)) BootHeader = {
    .header = "PC-FX:Hu_CD-ROM ",
    .unk = {
#include "boot.h"
    },
    .title = "",
    .sect_off = 0,
    .sect_count = 0,
    .prog_off = 0,
    .prog_point = 0,
    .maker_id = "N/A",
    .maker_name = "pcfx-cdlink",
    .volume_no = 0,
    .version = 0x0100,
    .country = 1,
    .date = "20XX0131",
    .pad = { 0, },
    .udata = { 0, }
};

typedef struct {
    char path[512];
    uint32_t lba;
    uint32_t sectors;
    uint64_t size;
} CdFile;

static uint32_t sectors_for_size(uint64_t size)
{
    return (uint32_t)((size + (SECTOR_SIZE - 1u)) / SECTOR_SIZE);
}

static int file_size(const char *path, uint64_t *out_size)
{
    struct stat st;
    if(stat(path, &st) != 0) {
        perror(path);
        return -1;
    }
    *out_size = (uint64_t)st.st_size;
    return 0;
}

static void trim_eol(char *s)
{
    int i = (int)strlen(s) - 1;
    while(i >= 0 && (s[i] == '\n' || s[i] == '\r' || s[i] == ' ' || s[i] == '\t')) {
        s[i--] = 0;
    }
}

static void copy_field(char *dst, size_t dst_size, const char *src)
{
    snprintf(dst, dst_size, "%s", src);
    trim_eol(dst);
    if(dst_size > 0) dst[dst_size - 1] = 0;
}

static void cleanup_name(const char *input, char *out, size_t out_size)
{
    size_t j = 0;
    size_t i;
    for(i = 0; input[i] && j + 1 < out_size; i++) {
        unsigned char c = (unsigned char)input[i];
        if(!isalnum(c)) c = '_';
        out[j++] = (char)toupper(c);
    }
    out[j] = 0;
}

static int write_zeroes(FILE *out_fp, uint64_t count)
{
    static const unsigned char zero[SECTOR_SIZE] = {0};
    while(count > 0) {
        size_t chunk = count > sizeof(zero) ? sizeof(zero) : (size_t)count;
        if(fwrite(zero, 1, chunk, out_fp) != chunk) {
            perror("writing zero padding");
            return -1;
        }
        count -= chunk;
    }
    return 0;
}

static int write_file_padded(FILE *out_fp, const char *path, uint32_t sectors_to_write)
{
    unsigned char buf[32768];
    FILE *in_fp = fopen(path, "rb");
    uint64_t written = 0;
    uint64_t target = (uint64_t)sectors_to_write * SECTOR_SIZE;
    if(!in_fp) {
        perror(path);
        return -1;
    }
    for(;;) {
        size_t got = fread(buf, 1, sizeof(buf), in_fp);
        if(got > 0) {
            if(written + got > target) got = (size_t)(target - written);
            if(got > 0 && fwrite(buf, 1, got, out_fp) != got) {
                perror("writing file data");
                fclose(in_fp);
                return -1;
            }
            written += got;
            if(written == target) break;
        }
        if(got < sizeof(buf)) {
            if(ferror(in_fp)) {
                perror("reading file data");
                fclose(in_fp);
                return -1;
            }
            break;
        }
    }
    fclose(in_fp);
    if(written < target) {
        if(write_zeroes(out_fp, target - written) != 0) return -1;
    }
    return 0;
}

#define MAX_WAV_FILES 64

typedef struct {
    char dir[256];
    char name[256];
} WavEntry;

static int ends_with_wav(const char *name)
{
    size_t n = strlen(name);
    return n > 4 && name[n-4] == '.' &&
           ((name[n-3]|0x20) == 'w') &&
           ((name[n-2]|0x20) == 'a') &&
           ((name[n-1]|0x20) == 'v');
}

static int wav_cmp(const void *a, const void *b)
{
    return strcmp(((const WavEntry*)a)->name, ((const WavEntry*)b)->name);
}

static int scan_wav_dir(const char *dirpath, WavEntry *entries, int *count)
{
#ifndef _WIN32
    DIR *d = opendir(dirpath);
    struct dirent *ent;
    if (!d) return 0;
    while ((ent = readdir(d)) != NULL && *count < MAX_WAV_FILES) {
        if (ends_with_wav(ent->d_name)) {
            snprintf(entries[*count].dir, sizeof(entries[*count].dir), "%s", dirpath);
            snprintf(entries[*count].name, sizeof(entries[*count].name), "%s", ent->d_name);
            (*count)++;
        }
    }
    closedir(d);
    return 1;
#else
    (void)dirpath; (void)entries; (void)count;
    return 0;
#endif
}

static void cleanup_wav_stem(const char *filename, char *out, size_t out_size)
{
    char base[512];
    char *dot;
    snprintf(base, sizeof(base), "%s", filename);
    dot = strrchr(base, '.');
    if (dot) *dot = 0;
    cleanup_name(base, out, out_size);
}

static int write_cdda_header(const char *path, WavEntry *wavs, int wav_count, int first_track)
{
    int i;
    FILE *hfp = fopen(path, "wb");
    if (!hfp) {
        perror(path);
        return -1;
    }
    fprintf(hfp, "#ifndef _CDDA_TRACKS_H_\n#define _CDDA_TRACKS_H_\n\n");
    for (i = 0; i < wav_count; i++) {
        char stem[512];
        cleanup_wav_stem(wavs[i].name, stem, sizeof(stem));
        fprintf(hfp, "#define CDDA_TRACK_%s %d\n", stem, first_track + i);
    }
    fprintf(hfp, "\n#endif /* _CDDA_TRACKS_H_ */\n");
    fclose(hfp);
    return 0;
}

/* --- WAV decode + resample to Red Book CD audio (44100 Hz, 16-bit, stereo) --- */

#define CD_AUDIO_RATE   44100u
#define CD_AUDIO_SECTOR 2352u   /* 588 stereo 16-bit frames */

static uint16_t rd_u16le(const unsigned char *p) { return (uint16_t)(p[0] | (p[1] << 8)); }
static uint32_t rd_u32le(const unsigned char *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}

/* Decode a WAV file to interleaved stereo float at its native rate.
   Supports 8/16/24/32-bit PCM and 32-bit IEEE float, mono or multi-channel
   (extra channels past the first two are dropped).  Returns 0 on success. */
static int wav_load_stereo_float(const char *path, float **out, size_t *out_frames,
                                 uint32_t *out_rate)
{
    FILE *f = fopen(path, "rb");
    unsigned char *buf = NULL;
    long fsize;
    uint16_t fmt = 0, channels = 0, bits = 0;
    uint32_t rate = 0;
    size_t data_off = 0, data_len = 0;
    size_t pos;
    int have_fmt = 0, have_data = 0;

    if(!f) { perror(path); return -1; }
    if(fseek(f, 0, SEEK_END) != 0) { fclose(f); return -1; }
    fsize = ftell(f);
    if(fsize < 44) { fprintf(stderr, "%s: too small for a WAV\n", path); fclose(f); return -1; }
    rewind(f);
    buf = malloc((size_t)fsize);
    if(!buf) { fclose(f); return -1; }
    if(fread(buf, 1, (size_t)fsize, f) != (size_t)fsize) { perror(path); free(buf); fclose(f); return -1; }
    fclose(f);

    if(memcmp(buf, "RIFF", 4) != 0 || memcmp(buf + 8, "WAVE", 4) != 0) {
        fprintf(stderr, "%s: not a RIFF/WAVE file\n", path);
        free(buf);
        return -1;
    }

    pos = 12;
    while(pos + 8 <= (size_t)fsize) {
        const unsigned char *id = buf + pos;
        uint32_t csize = rd_u32le(buf + pos + 4);
        size_t body = pos + 8;
        if(body + csize > (size_t)fsize) csize = (uint32_t)((size_t)fsize - body);
        if(memcmp(id, "fmt ", 4) == 0 && csize >= 16) {
            fmt      = rd_u16le(buf + body + 0);
            channels = rd_u16le(buf + body + 2);
            rate     = rd_u32le(buf + body + 4);
            bits     = rd_u16le(buf + body + 14);
            if(fmt == 0xFFFE && csize >= 18) {
                /* WAVE_FORMAT_EXTENSIBLE: real format is in the GUID's first word. */
                uint16_t ext = rd_u16le(buf + body + 16);
                (void)ext;
                fmt = rd_u16le(buf + body + 24); /* SubFormat low word */
            }
            have_fmt = 1;
        } else if(memcmp(id, "data", 4) == 0) {
            data_off = body;
            data_len = csize;
            have_data = 1;
        }
        pos = body + csize + (csize & 1u); /* chunks are word-aligned */
    }

    if(!have_fmt || !have_data || channels == 0 || rate == 0) {
        fprintf(stderr, "%s: missing/invalid fmt or data chunk\n", path);
        free(buf);
        return -1;
    }
    if(fmt != 1 && fmt != 3) {
        fprintf(stderr, "%s: unsupported WAV format 0x%X (need PCM or float)\n", path, fmt);
        free(buf);
        return -1;
    }

    {
        unsigned bytes_per_sample = bits / 8u;
        size_t frame_bytes = (size_t)bytes_per_sample * channels;
        size_t frames, i;
        float *dst;
        const unsigned char *src;

        if(bytes_per_sample == 0 || frame_bytes == 0) {
            fprintf(stderr, "%s: bad bit depth %u\n", path, bits);
            free(buf);
            return -1;
        }
        frames = data_len / frame_bytes;
        dst = malloc(frames * 2 * sizeof(float));
        if(!dst) { free(buf); return -1; }

        for(i = 0; i < frames; i++) {
            int ch;
            for(ch = 0; ch < 2; ch++) {
                int sch = (channels == 1) ? 0 : ch; /* mono -> dup, else L/R */
                src = buf + data_off + i * frame_bytes + (size_t)sch * bytes_per_sample;
                float v = 0.0f;
                if(fmt == 3 && bits == 32) {
                    union { uint32_t u; float fl; } cv;
                    cv.u = rd_u32le(src);
                    v = cv.fl;
                } else if(bits == 16) {
                    v = (float)(int16_t)rd_u16le(src) / 32768.0f;
                } else if(bits == 8) {
                    v = ((float)src[0] - 128.0f) / 128.0f; /* 8-bit PCM is unsigned */
                } else if(bits == 24) {
                    int32_t s = (int32_t)((uint32_t)src[0] | ((uint32_t)src[1] << 8) |
                                          ((uint32_t)src[2] << 16));
                    if(s & 0x800000) s |= ~0xFFFFFF; /* sign-extend */
                    v = (float)s / 8388608.0f;
                } else if(bits == 32) {
                    v = (float)(int32_t)rd_u32le(src) / 2147483648.0f;
                } else {
                    fprintf(stderr, "%s: unsupported bit depth %u\n", path, bits);
                    free(dst);
                    free(buf);
                    return -1;
                }
                dst[i * 2 + ch] = v;
            }
        }
        free(buf);
        *out = dst;
        *out_frames = frames;
        *out_rate = rate;
        return 0;
    }
}

static int16_t f_to_s16(float v)
{
    float s = v * 32767.0f;
    s += (s >= 0.0f) ? 0.5f : -0.5f;
    if(s > 32767.0f) s = 32767.0f;
    if(s < -32768.0f) s = -32768.0f;
    return (int16_t)s;
}

/* Linear-resample interleaved stereo float to 44100 Hz signed-16 stereo. */
static int resample_to_cd_s16(const float *in, size_t in_frames, uint32_t in_rate,
                              int16_t **out, size_t *out_frames)
{
    size_t out_n, i;
    int16_t *dst;

    if(in_rate == CD_AUDIO_RATE) {
        out_n = in_frames;
        dst = malloc(out_n * 2 * sizeof(int16_t) + 4);
        if(!dst) return -1;
        for(i = 0; i < out_n; i++) {
            dst[i * 2 + 0] = f_to_s16(in[i * 2 + 0]);
            dst[i * 2 + 1] = f_to_s16(in[i * 2 + 1]);
        }
    } else {
        double ratio = (double)in_rate / (double)CD_AUDIO_RATE;
        out_n = (size_t)((double)in_frames / ratio);
        dst = malloc(out_n * 2 * sizeof(int16_t) + 4);
        if(!dst) return -1;
        for(i = 0; i < out_n; i++) {
            double sp = (double)i * ratio;
            size_t idx = (size_t)sp;
            double frac = sp - (double)idx;
            size_t nxt = (idx + 1 < in_frames) ? idx + 1 : idx;
            int ch;
            for(ch = 0; ch < 2; ch++) {
                float a = in[idx * 2 + ch];
                float b = in[nxt * 2 + ch];
                dst[i * 2 + ch] = f_to_s16(a + (b - a) * (float)frac);
            }
        }
    }
    *out = dst;
    *out_frames = out_n;
    return 0;
}

/* Write raw CD audio sectors (LE s16 stereo), zero-padded to a 2352-byte
   sector. If pregap_sectors is nonzero, that many silent 2352-byte sectors
   are physically written FIRST (real embedded-bytes pregap, addressed via
   the cue's INDEX 00/01 pair within this same file). */
static int write_audio_bin(const char *path, const int16_t *pcm, size_t frames, uint32_t pregap_sectors)
{
    FILE *f = fopen(path, "wb");
    uint64_t bytes = (uint64_t)frames * 4u;
    uint64_t padded = ((bytes + CD_AUDIO_SECTOR - 1u) / CD_AUDIO_SECTOR) * CD_AUDIO_SECTOR;
    if(!f) { perror(path); return -1; }
    if(pregap_sectors && write_zeroes(f, (uint64_t)pregap_sectors * CD_AUDIO_SECTOR) != 0) {
        fclose(f);
        return -1;
    }
    if(bytes && fwrite(pcm, 1, (size_t)bytes, f) != (size_t)bytes) {
        perror(path);
        fclose(f);
        return -1;
    }
    if(write_zeroes(f, padded - bytes) != 0) { fclose(f); return -1; }
    fclose(f);
    return 0;
}

/* Return 1 if binpath exists and is newer than wavpath (mtime comparison). */
static int bin_is_fresh(const char *wavpath, const char *binpath)
{
    struct stat sw, sb;
    if(stat(wavpath, &sw) != 0 || stat(binpath, &sb) != 0) return 0;
    /* use st_mtime; on Linux st_mtim gives nanoseconds but we only need seconds */
    return sb.st_mtime > sw.st_mtime;
}

/* Decode wavpath, resample to CD audio, and write binpath, optionally with
   pregap_sectors of silence physically embedded ahead of the real audio.
   If the bin already exists and is newer than the wav, skip conversion and
   just measure the existing bin.  Returns 0 on success. */
static int convert_wav_to_cd_bin_pregap(const char *wavpath, const char *binpath,
                                        uint32_t pregap_sectors, uint32_t *out_sectors)
{
    if(bin_is_fresh(wavpath, binpath)) {
        /* Reuse existing bin — just measure its size for the sector count. */
        struct stat sb;
        if(stat(binpath, &sb) == 0 && sb.st_size > 0) {
            if(out_sectors)
                *out_sectors = (uint32_t)(((uint64_t)sb.st_size + CD_AUDIO_SECTOR - 1u) / CD_AUDIO_SECTOR);
            printf("CDDA (cached): %s\n", binpath);
            return 0;
        }
    }

    {
        float *fbuf = NULL;
        int16_t *pcm = NULL;
        size_t in_frames = 0, out_frames = 0;
        uint32_t rate = 0;

        if(wav_load_stereo_float(wavpath, &fbuf, &in_frames, &rate) != 0) return -1;
        if(resample_to_cd_s16(fbuf, in_frames, rate, &pcm, &out_frames) != 0) {
            free(fbuf);
            return -1;
        }
        free(fbuf);
        if(write_audio_bin(binpath, pcm, out_frames, pregap_sectors) != 0) { free(pcm); return -1; }
        free(pcm);
        if(out_sectors)
            *out_sectors = pregap_sectors +
                (uint32_t)(((uint64_t)out_frames * 4u + CD_AUDIO_SECTOR - 1u) / CD_AUDIO_SECTOR);
        return 0;
    }
}

static int convert_wav_to_cd_bin(const char *wavpath, const char *binpath, uint32_t *out_sectors)
{
    return convert_wav_to_cd_bin_pregap(wavpath, binpath, 0, out_sectors);
}

static int write_lba_header(const char *path, CdFile *files, int file_count)
{
    int i;
    FILE *hfp = fopen(path, "wb");
    if(!hfp) {
        perror(path);
        return -1;
    }
    fprintf(hfp, "#ifndef _BINCAT_OUTPUT_H_\n#define _BINCAT_OUTPUT_H_\n\ntypedef enum {\n");
    for(i = 0; i < file_count; i++) {
        char clean[768];
        cleanup_name(files[i].path, clean, sizeof(clean));
        fprintf(hfp, "\tBINARY_LBA_%s = %u,\n", clean, files[i].lba);
    }
    fprintf(hfp, "} bincat_lbas;\n\n");
    for(i = 0; i < file_count; i++) {
        char clean[768];
        cleanup_name(files[i].path, clean, sizeof(clean));
        fprintf(hfp, "#define BINARY_LBA_%s %u\n", clean, files[i].lba);
    }
    fprintf(hfp, "#endif\n\n");
    fclose(hfp);
    return 0;
}

int main(int argc, char *argv[])
{
    if(argc < 3) {
        printf("Usage: %s input.txt outfiles\n", argv[0]);
        return EXIT_FAILURE;
    }

    FILE* fp = fopen(argv[1], "r");
    if(fp == NULL) {
        perror("Opening input list");
        return EXIT_FAILURE;
    }

    char tmpbuf[1024];
    char binname[512] = "\0";
    char lbaheader[512] = "\0";
    char cddaheader[512] = "\0";
    char cddadir[512] = "\0";
    char track1audio[512] = "\0";
    int binblocks = 0;
    CdFile files[MAX_APPEND_FILES + 1];
    int file_count = 0;
    int append_count = 0;

    while(fgets(tmpbuf, sizeof(tmpbuf), fp) != NULL) {
        trim_eol(tmpbuf);
        if(tmpbuf[0] == 0 || tmpbuf[0] == '#') continue;
        if(memcmp(tmpbuf, "binary ", 7) == 0) {
            copy_field(binname, sizeof(binname), tmpbuf + 7);
        } else if(memcmp(tmpbuf, "blocks ", 7) == 0) {
            binblocks = atoi(tmpbuf + 7);
        } else if(memcmp(tmpbuf, "append ", 7) == 0 || memcmp(tmpbuf, "asset ", 6) == 0) {
            const char *path = (tmpbuf[0] == 'a' && tmpbuf[1] == 'p') ? tmpbuf + 7 : tmpbuf + 6;
            if(append_count >= MAX_APPEND_FILES) {
                fprintf(stderr, "Too many append/asset files; max %d\n", MAX_APPEND_FILES);
                fclose(fp);
                return EXIT_FAILURE;
            }
            copy_field(files[1 + append_count].path, sizeof(files[1 + append_count].path), path);
            append_count++;
        } else if(memcmp(tmpbuf, "lbaheader ", 10) == 0) {
            copy_field(lbaheader, sizeof(lbaheader), tmpbuf + 10);
        } else if(memcmp(tmpbuf, "cddaheader ", 11) == 0) {
            copy_field(cddaheader, sizeof(cddaheader), tmpbuf + 11);
        } else if(memcmp(tmpbuf, "cddadir ", 8) == 0) {
            copy_field(cddadir, sizeof(cddadir), tmpbuf + 8);
        } else if(memcmp(tmpbuf, "track1audio ", 12) == 0) {
            copy_field(track1audio, sizeof(track1audio), tmpbuf + 12);
        } else if(memcmp(tmpbuf, "name ", 5) == 0) {
            copy_field(BootHeader.title, 0x20, tmpbuf + 5);
            BootHeader.title[0x1F] = 0;
        } else if(memcmp(tmpbuf, "makerid ", 8) == 0) {
            copy_field(BootHeader.maker_id, 4, tmpbuf + 8);
            BootHeader.maker_id[3] = 0;
        } else if(memcmp(tmpbuf, "maker ", 6) == 0) {
            copy_field(BootHeader.maker_name, 60, tmpbuf + 6);
            BootHeader.maker_name[59] = 0;
        } else if(memcmp(tmpbuf, "date ", 5) == 0) {
            copy_field(BootHeader.date, 8, tmpbuf + 5);
        } else if(memcmp(tmpbuf, "country ", 8) == 0) {
            BootHeader.country = atoi(tmpbuf + 8);
        } else if(memcmp(tmpbuf, "version ", 8) == 0) {
            BootHeader.version = atoi(tmpbuf + 8);
        } else {
            fprintf(stderr, "Warning: unknown directive ignored: %s\n", tmpbuf);
        }
    }
    fclose(fp);

    if(binname[0] == 0) {
        fprintf(stderr, "No binary name\n");
        return EXIT_FAILURE;
    }

    snprintf(files[0].path, sizeof(files[0].path), "%s", binname);
    file_count = append_count + 1;

    int i;
    for(i = 0; i < file_count; i++) {
        if(file_size(files[i].path, &files[i].size) != 0) return EXIT_FAILURE;
        files[i].sectors = sectors_for_size(files[i].size);
    }

    if(binblocks == 0)
        binblocks = (int)files[0].sectors;
    if((uint32_t)binblocks < files[0].sectors) {
        fprintf(stderr, "blocks %d is smaller than boot binary sector size %u\n", binblocks, files[0].sectors);
        return EXIT_FAILURE;
    }
    files[0].sectors = (uint32_t)binblocks;

    /* If a track1audio warning/lead track is configured, it (and the real
       2-second pregap embedded ahead of the data track) physically precedes
       the data track on the disc, so every disc-absolute LBA we bake for our
       own runtime (lbaheader -> the CD DMA reader) needs that length added as a
       base offset. BootHeader.sect_off/prog_off stay track-relative (the
       BIOS resolves the data track's own start via the TOC), so they are
       untouched below. */
    char track1_binpath[600] = "";
    uint32_t track1_sectors = 0;
    if(track1audio[0]) {
        snprintf(track1_binpath, sizeof(track1_binpath), "%s_t01.bin", argv[2]);
        if(convert_wav_to_cd_bin(track1audio, track1_binpath, &track1_sectors) != 0) {
            fprintf(stderr, "Failed to convert track1audio: %s\n", track1audio);
            return EXIT_FAILURE;
        }
        printf("CDDA Track 01 (lead/warning track): %s -> %s (%u sectors, 44100Hz/16-bit/stereo)\n",
               track1audio, track1_binpath, track1_sectors);
    }
    uint32_t lba_base = BOOT_SECTORS;
    if(track1audio[0]) lba_base += track1_sectors + DATA_PREGAP_SECTORS;

    uint32_t cur_lba = lba_base;
    for(i = 0; i < file_count; i++) {
        files[i].lba = cur_lba;
        cur_lba += files[i].sectors;
    }

    uint32_t sector_offset = BOOT_SECTORS;
    uint32_t sector_count = (uint32_t)binblocks;
    uint32_t prog_offset = 0x8000;
    uint32_t prog_point = 0x8000;

    printf("Boot program size: %llu bytes, %u sectors loaded to RAM\n",
           (unsigned long long)files[0].size, sector_count);
    if(file_count > 1) {
        printf("External CD assets: %d files, %u sectors not loaded by boot header\n",
               file_count - 1, cur_lba - lba_base - sector_count);
    }
    int32_t sh_size = (1024 * 2048) - ((int32_t)sector_count * 2048) - 0x8000 - 2048;
    if(sh_size < 0) {
        fprintf(stderr, "Program size is too large\n");
        return EXIT_FAILURE;
    }
    printf("Stack+heap Free Space: %d\n", sh_size);

    BootHeader.sect_off = le32(sector_offset);
    BootHeader.sect_count = le32(sector_count);
    BootHeader.prog_off = le32(prog_offset);
    BootHeader.prog_point = le32(prog_point);
    BootHeader.volume_no = le32(BootHeader.volume_no);
    BootHeader.version = le16(BootHeader.version);
    BootHeader.country = le16(BootHeader.country);

    char *obinname = malloc(strlen(argv[2]) + 5);
    sprintf(obinname, "%s.bin", argv[2]);
    FILE *out_fp = fopen(obinname, "wb");
    if(!out_fp) {
        perror("Error opening output file");
        free(obinname);
        return EXIT_FAILURE;
    }

    if(track1audio[0]) {
        /* Real (non-synthesized) 2-second pregap physically embedded ahead
           of the data track's own content, addressed via the cue's own
           INDEX 00/01 pair within this same file -- BIOS/BootHeader-relative
           offsets (sect_off etc.) are unaffected since they count from
           INDEX 01, not from byte 0 of the file. */
        if(write_zeroes(out_fp, (uint64_t)DATA_PREGAP_SECTORS * SECTOR_SIZE) != 0) {
            fclose(out_fp);
            free(obinname);
            return EXIT_FAILURE;
        }
    }

    if(fwrite(&BootHeader, 1, sizeof(BootHeader), out_fp) != sizeof(BootHeader)) {
        perror("writing boot header");
        fclose(out_fp);
        free(obinname);
        return EXIT_FAILURE;
    }

    for(i = 0; i < file_count; i++) {
        printf("LBA %u: %s (%llu bytes, %u sectors)%s\n",
               files[i].lba, files[i].path, (unsigned long long)files[i].size,
               files[i].sectors, i == 0 ? " [boot-load]" : "");
        if(write_file_padded(out_fp, files[i].path, files[i].sectors) != 0) {
            fclose(out_fp);
            free(obinname);
            return EXIT_FAILURE;
        }
    }

    uint32_t total_sectors = cur_lba;
    if(total_sectors < MIN_DISC_SECTORS) {
        uint32_t pad_sectors = MIN_DISC_SECTORS - total_sectors;
        if(write_zeroes(out_fp, (uint64_t)pad_sectors * SECTOR_SIZE) != 0) {
            fclose(out_fp);
            free(obinname);
            return EXIT_FAILURE;
        }
        total_sectors = MIN_DISC_SECTORS;
    }
    fclose(out_fp);

    if(lbaheader[0]) {
        if(write_lba_header(lbaheader, files, file_count) != 0) {
            free(obinname);
            return EXIT_FAILURE;
        }
        printf("Wrote LBA header: %s\n", lbaheader);
    }

    /* Scan for WAV audio tracks. An explicit `cddadir` wins; otherwise fall
       back to the conventional directory names, relative to CWD. */
    static const char *wav_scan_dirs[] = {
        "Music", "music", "MUSIC", "cdda", "CDDA", NULL
    };
    WavEntry wav_entries[MAX_WAV_FILES];
    int wav_count = 0;
    int di;
    if(cddadir[0]) {
        if(!scan_wav_dir(cddadir, wav_entries, &wav_count)) {
            fprintf(stderr, "cddadir: cannot open directory: %s\n", cddadir);
            return EXIT_FAILURE;
        }
        if(wav_count == 0)
            fprintf(stderr, "Warning: cddadir has no .wav files: %s\n", cddadir);
    } else {
        for(di = 0; wav_scan_dirs[di] != NULL; di++) {
            if(scan_wav_dir(wav_scan_dirs[di], wav_entries + wav_count, &wav_count))
                break; /* use first directory that exists and has WAVs */
        }
    }
    if(wav_count > 1)
        qsort(wav_entries, (size_t)wav_count, sizeof(WavEntry), wav_cmp);

    char *cuename = malloc(strlen(argv[2]) + 5);
    sprintf(cuename, "%s.cue", argv[2]);
    fp = fopen(cuename, "wb");
    if(!fp) {
        perror("Error opening cue file");
        free(cuename);
        free(obinname);
        return EXIT_FAILURE;
    }
    /* Track layout matches every retail/PC-FXGA disc surveyed (Team
       Innocent, N-nyuu, Same Game FX): audio track 01 first (a short
       lead/warning track, same convention as "do not play this track on a
       CD player"), then the MODE1 data track. A real (embedded-bytes)
       2-second pregap sits at the audio1->data2 boundary and again at the
       data2->first-CDDA-track boundary, expressed as INDEX 00/01 within the
       track's own file - never a synthesized PREGAP line, and never on
       audio-to-audio splices. If no track1audio is configured, fall back to
       the old data-track-first layout with no pregaps at all. */
    int first_cdda_track;
    if(track1audio[0]) {
        fprintf(fp, "FILE \"%s\" BINARY\n", track1_binpath);
        fprintf(fp, "  TRACK 01 AUDIO\n");
        fprintf(fp, "    INDEX 01 00:00:00\n");
        fprintf(fp, "FILE \"%s\" BINARY\n", obinname);
        fprintf(fp, "  TRACK 02 MODE1/2048\n");
        fprintf(fp, "    INDEX 00 00:00:00\n");
        fprintf(fp, "    INDEX 01 00:02:00\n");
        first_cdda_track = 3;
    } else {
        fprintf(fp, "FILE \"%s\" BINARY\n", obinname);
        fprintf(fp, "  TRACK 01 MODE1/2048\n");
        fprintf(fp, "    INDEX 01 00:00:00\n");
        first_cdda_track = 2;
    }
    for(i = 0; i < wav_count; i++) {
        char wavpath[600];
        char binpath[600];
        char stem[512];
        uint32_t sectors = 0;
        int track_num = first_cdda_track + i;
        /* Only the CD-DA track immediately following the data track carries
           the embedded pregap - every later audio-to-audio splice gets none. */
        int needs_pregap = track1audio[0] && (i == 0);
        snprintf(wavpath, sizeof(wavpath), "%s/%s", wav_entries[i].dir, wav_entries[i].name);
        /* Keyed by the wav's own stem, NOT track_num: track_num is positional
           and shifts whenever the track layout changes (e.g. adding/removing
           track1audio moves every CD-DA track up or down by one). Naming the
           cache file after the track number let a stale bin from a previous
           layout - still newer than its wav per mtime - get silently reused
           under a NEW track number, splicing a different song's audio onto
           that track. Naming it after the source file's identity instead
           means bin_is_fresh() below can only ever compare a wav against the
           bin that was actually converted from it. */
        cleanup_wav_stem(wav_entries[i].name, stem, sizeof(stem));
        snprintf(binpath, sizeof(binpath), "%s_%s.bin", argv[2], stem);
        if(convert_wav_to_cd_bin_pregap(wavpath, binpath, needs_pregap ? DATA_PREGAP_SECTORS : 0, &sectors) != 0) {
            fprintf(stderr, "Failed to convert audio track: %s\n", wavpath);
            fclose(fp);
            free(cuename);
            free(obinname);
            return EXIT_FAILURE;
        }
        /* ImgBurn-style layout: each CD-DA track is its own raw 2352-byte
           BINARY file, signed-16 LE stereo at 44100 Hz. */
        fprintf(fp, "FILE \"%s\" BINARY\n", binpath);
        fprintf(fp, "  TRACK %02d AUDIO\n", track_num);
        if(needs_pregap) {
            fprintf(fp, "    INDEX 00 00:00:00\n");
            fprintf(fp, "    INDEX 01 00:02:00\n");
        } else {
            fprintf(fp, "    INDEX 01 00:00:00\n");
        }
        printf("CDDA Track %02d: %s -> %s (%u sectors, 44100Hz/16-bit/stereo)\n",
               track_num, wavpath, binpath, sectors);
    }
    fclose(fp);
    free(cuename);
    free(obinname);

    if(cddaheader[0] && wav_count > 0) {
        if(write_cdda_header(cddaheader, wav_entries, wav_count, first_cdda_track) != 0)
            return EXIT_FAILURE;
        printf("Wrote CDDA track header: %s\n", cddaheader);
    }

    printf("Total disc sectors: %u\n", total_sectors);
    printf("Done. Boot header sect_count excludes append/asset files.\n");
    return EXIT_SUCCESS;
}
