#!/usr/bin/env python3
"""SRT paper video: strict timing, editable regions, raster stroke reveal, FFmpeg."""
from __future__ import annotations
import argparse
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

BG = (245, 235, 215)
STAMP = re.compile(r'^(\d+):(\d{2}):(\d{2})[,.](\d{3})$')


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def milliseconds(text):
    match = STAMP.fullmatch(text.strip())
    if not match:
        raise ValueError(f'无效时间戳: {text}')
    h, m, s, ms = map(int, match.groups())
    if m > 59 or s > 59:
        raise ValueError(f'无效时间戳: {text}')
    return ((h * 60 + m) * 60 + s) * 1000 + ms


def parse_srt(path):
    text = Path(path).read_text(encoding='utf-8-sig').strip().replace('\r\n', '\n')
    cues = []
    for block in re.split(r'\n\s*\n', text):
        lines = block.strip().splitlines()
        if lines and lines[0].strip().isdigit():
            lines = lines[1:]
        if len(lines) < 2 or '-->' not in lines[0]:
            raise ValueError(f'无效字幕块: {block[:100]}')
        left, right = lines[0].split('-->', 1)
        start, end = milliseconds(left), milliseconds(right.split()[0])
        content = '\n'.join(lines[1:]).strip()
        if not content or end <= start or (cues and start < cues[-1]['endMs']):
            raise ValueError('字幕为空、时间倒置或字幕重叠；请先修正 SRT')
        cues.append(dict(id=len(cues) + 1, startMs=start, endMs=end, text=content))
    if not cues:
        raise ValueError('字幕为空')
    return cues


def plan(srt, output, target):
    if target <= 0:
        raise ValueError('target-sec 必须大于零')
    cues = parse_srt(srt)
    groups, current = [], []
    for cue in cues:
        if current and cue['endMs'] - current[0]['startMs'] > target * 1000:
            groups.append(current)
            current = []
        current.append(cue)
    if current:
        groups.append(current)
    scenes = []
    for i, group in enumerate(groups):
        # First scene includes initial silence; gaps belong to preceding scene.
        start = 0 if i == 0 else group[0]['startMs']
        end = groups[i + 1][0]['startMs'] if i + 1 < len(groups) else cues[-1]['endMs'] + 500
        scenes.append(dict(id=f'scene-{i + 1:02d}', startMs=start, endMs=end,
                           durationMs=end - start, image=f'scene-{i + 1:02d}.png',
                           annotation=f'scene-{i + 1:02d}.json',
                           cues=[dict(c, localStartMs=c['startMs'] - start,
                                      localEndMs=c['endMs'] - start) for c in group],
                           coreIdea='', imagePrompt=''))
    write_json(output, dict(version=1, sourceSrt=str(Path(srt).resolve()),
                            durationMs=scenes[-1]['endMs'], scenes=scenes))
    print(f'PLAN={output} SCENES={len(scenes)}')


def integer(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f'{label} 必须是 >= {minimum} 的整数')
    return value


def rect(value, w, h):
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError('区域需为 [x,y,width,height]')
    x, y, rw, rh = [integer(v, '区域坐标') for v in value]
    if rw < 1 or rh < 1 or x + rw > w or y + rh > h:
        raise ValueError(f'区域超出画布: {value}')
    return x, y, rw, rh


def validate(image, annotation):
    with Image.open(image) as im:
        w, h = im.size
    if annotation.get('canvas') != [w, h]:
        raise ValueError(f'canvas 必须等于原图尺寸 {[w, h]}')
    duration = integer(annotation.get('durationMs'), 'durationMs', 501)
    elements = annotation.get('elements')
    if not isinstance(elements, list) or not elements:
        raise ValueError('elements 不能为空')
    previous = 0
    seen = set()
    for e in elements:
        if not isinstance(e.get('id'), str) or not e['id'] or e['id'] in seen:
            raise ValueError('元素 id 需为唯一非空字符串')
        seen.add(e['id'])
        rect(e['region'], w, h)
        for protected in e.get('protected', []):
            rect(protected, w, h)
        start = integer(e['startMs'], 'startMs')
        end = integer(e['endMs'], 'endMs', 1)
        if start < previous or end <= start or end > duration - 500:
            raise ValueError('元素必须串行作画，且最后保留至少 500ms 完整画面')
        previous = end
        if not isinstance(e.get('subtitle'), str) or not e['subtitle'].strip():
            raise ValueError('每个元素需关联 subtitle')
    return w, h


def annotation_template(image, output, duration):
    with Image.open(image) as im:
        w, h = im.size
    write_json(output, dict(version=1, canvas=[w, h], durationMs=duration, elements=[
        dict(id='element-1', label='请按字幕事件拆分区域', subtitle='请填入对应的原字幕',
             region=[0, 0, w, h], startMs=0, endMs=duration - 500, protected=[])]))


def region_mask(region, size):
    w, h = size
    mask = np.zeros((h, w), dtype=bool)
    x, y, rw, rh = region
    mask[y:y + rh, x:x + rw] = True
    return mask


def stroke_paths(mask, step):
    """Serpentine runs over actual dark pixels; disjoint runs lift the pen."""
    paths = []
    for row, y in enumerate(range(0, mask.shape[0], step)):
        xs = np.flatnonzero(mask[y])
        if not len(xs):
            continue
        breaks = np.flatnonzero(np.diff(xs) > 1) + 1
        runs = np.split(xs, breaks)
        if row % 2:
            runs = [r[::-1] for r in runs[::-1]]
        for run in runs:
            paths.append([(int(run[0]), y), (int(run[-1]), y)])
    return paths


def reveal_path(draw, paths, begin, finish, width):
    """Advance a normalized stroke distance; reveal only newly traversed segments."""
    lengths = [max(1, abs(p[1][0] - p[0][0])) for p in paths]
    total = sum(lengths)
    if not total:
        return None
    low, high = begin * total, finish * total
    offset, tip = 0, None
    for (a, b), length in zip(paths, lengths):
        end = offset + length
        if end > low and offset <= high:
            u, v = max(0, (low - offset) / length), min(1, (high - offset) / length)
            if v >= u:
                x1 = round(a[0] + (b[0] - a[0]) * u)
                x2 = round(a[0] + (b[0] - a[0]) * v)
                draw.line([(x1, a[1]), (x2, a[1])], fill=255, width=width)
                tip = (x2, a[1])
        offset = end
        if offset > high:
            break
    return tip


def render(image, annotation, output, fps=24, width=1280):
    if not shutil.which('ffmpeg'):
        raise ValueError('请安装 FFmpeg 并加入 PATH')
    validate(image, annotation)
    if not 1 <= fps <= 60 or width < 64 or width > 3840 or width % 2:
        raise ValueError('fps 范围 1–60；width 需为 64–3840 的偶数')
    source = Image.open(image).convert('RGB')
    scale = width / source.width
    height = max(2, round(source.height * scale / 2) * 2)
    source = source.resize((width, height), Image.Resampling.LANCZOS)
    rgb = np.array(source)
    background = np.full_like(rgb, BG)
    # Dark strokes only for the ink pass; the color pass restores source pixels.
    ink = rgb.min(axis=2) < 135
    gray = np.repeat(np.minimum(rgb.mean(axis=2), 90).astype(np.uint8)[:, :, None], 3, axis=2)
    elements, masks = annotation['elements'], []
    for e in elements:
        def scaled(r):
            x, y, rw, rh = r
            x0, y0 = round(x * width / annotation['canvas'][0]), round(y * height / annotation['canvas'][1])
            x1, y1 = round((x + rw) * width / annotation['canvas'][0]), round((y + rh) * height / annotation['canvas'][1])
            return [x0, y0, x1 - x0, y1 - y0]
        masks.append(region_mask(scaled(e['region']), (width, height)))
    allowed = []
    for i, e in enumerate(elements):
        mask = masks[i].copy()
        for later in masks[i + 1:]:
            mask &= ~later
        for r in e.get('protected', []):
            mask &= ~region_mask(scaled(r), (width, height))
        allowed.append(mask)
    covered = np.logical_or.reduce(allowed)
    # Reject uncovered content instead of introducing it abruptly at the end.
    content = np.max(np.abs(rgb.astype(int) - np.array(BG)), axis=2) > 45
    if np.count_nonzero(content & ~covered) > max(10, content.sum() * .005):
        raise ValueError('标注未覆盖所有画面内容，或保护区没有后续元素接管')
    paths = [stroke_paths(mask & ink, 2) for mask in allowed]
    layers = [Image.new('L', (width, height)) for _ in elements]
    previous = [0.0] * len(elements)
    count = math.ceil(annotation['durationMs'] * fps / 1000)
    output = Path(output)
    if output.exists():
        raise ValueError(f'输出已存在，请使用新文件名: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    command = ['ffmpeg', '-v', 'error', '-n', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
               '-s', f'{width}x{height}', '-r', str(fps), '-i', '-', '-an',
               '-c:v', 'libx264', '-crf', '18', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(output)]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        for frame in range(count):
            ms = frame * 1000 / fps
            canvas, tip = background.copy(), None
            for i, e in enumerate(elements):
                if ms <= e['startMs']:
                    continue
                progress = min(1, (ms - e['startMs']) / (e['endMs'] - e['startMs']))
                ink_progress = min(1, progress * 1.5)
                if ink_progress > previous[i]:
                    cursor = reveal_path(ImageDraw.Draw(layers[i]), paths[i], previous[i], ink_progress, 3)
                    if progress < 2 / 3:
                        tip = cursor
                    previous[i] = ink_progress
                visible_ink = (np.array(layers[i]) > 0) & allowed[i] & ink
                canvas[visible_ink] = gray[visible_ink]
                if progress > 2 / 3:
                    amount = (progress - 2 / 3) * 3
                    ys, xs = np.nonzero(allowed[i])
                    if len(ys):
                        bottom = ys.min() + math.ceil(amount * (ys.max() - ys.min() + 1))
                        color = allowed[i] & (np.arange(height)[:, None] < bottom)
                        canvas[color] = rgb[color]
                        if progress < 1:
                            row = max(0, min(height - 1, bottom - 1))
                            row_x = np.flatnonzero(allowed[i][row])
                            if len(row_x):
                                tip = (int(row_x[-1]), row)
                if progress == 1:
                    canvas[allowed[i]] = rgb[allowed[i]]
            final = Image.fromarray(canvas)
            if tip is not None:
                x, y = tip
                d = ImageDraw.Draw(final)
                d.line([(x, y), (x + 18, y - 32)], fill=(55, 55, 55), width=5)
                d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=(40, 40, 40))
            process.stdin.write(final.tobytes())
        process.stdin.close()
        error = process.stderr.read().decode()
        if process.wait():
            raise RuntimeError(error)
    except BaseException:
        process.kill()
        process.wait()
        output.unlink(missing_ok=True)
        raise
    print(f'VIDEO={output} FRAMES={count}')


def assemble(manifest, output, audio=None):
    data = read_json(manifest)
    root = Path(manifest).resolve().parent
    scenes = data['scenes']
    if not scenes:
        raise ValueError('scenes 为空')
    files = []
    expected_start = 0
    for s in scenes:
        if s['startMs'] != expected_start or s['endMs'] <= s['startMs']:
            raise ValueError('场景必须从零开始且首尾相接')
        expected_start = s['endMs']
        path = (root / s['video']).resolve()
        probe = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                '-of', 'json', str(path)], check=True, capture_output=True, text=True)
        actual = float(json.loads(probe.stdout)['format']['duration'])
        if abs(actual - (s['endMs'] - s['startMs']) / 1000) > .1:
            raise ValueError(f'场景时长不匹配: {path}')
        files.append(path)
    cmd = ['ffmpeg', '-v', 'error', '-n']
    for path in files:
        cmd += ['-i', str(path)]
    if audio:
        cmd += ['-i', str(Path(audio).resolve())]
    # Re-encode to avoid concat timestamp/extradata incompatibilities.
    inputs = ''.join(f'[{i}:v:0]' for i in range(len(files)))
    cmd += ['-filter_complex', inputs + f'concat=n={len(files)}:v=1:a=0[v]', '-map', '[v]']
    if audio:
        cmd += ['-map', f'{len(files)}:a:0', '-af', 'apad', '-c:a', 'aac']
    cmd += ['-t', str(expected_start / 1000), '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart', str(output)]
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, check=True)
    print(f'VIDEO={output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='command', required=True)
    p = subs.add_parser('plan')
    p.add_argument('srt'); p.add_argument('output'); p.add_argument('--target-sec', type=float, default=30)
    p = subs.add_parser('init')
    p.add_argument('image'); p.add_argument('output'); p.add_argument('--duration-ms', type=int, required=True)
    p = subs.add_parser('validate')
    p.add_argument('image'); p.add_argument('annotation')
    p = subs.add_parser('render')
    p.add_argument('image'); p.add_argument('annotation'); p.add_argument('output')
    p.add_argument('--fps', type=int, default=24); p.add_argument('--width', type=int, default=1280)
    p = subs.add_parser('assemble')
    p.add_argument('manifest'); p.add_argument('output'); p.add_argument('--audio')
    args = parser.parse_args()
    try:
        if args.command == 'plan': plan(args.srt, args.output, args.target_sec)
        elif args.command == 'init': annotation_template(args.image, args.output, args.duration_ms)
        elif args.command == 'validate':
            validate(args.image, read_json(args.annotation)); print('VALID')
        elif args.command == 'render': render(args.image, read_json(args.annotation), args.output, args.fps, args.width)
        else: assemble(args.manifest, args.output, args.audio)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f'错误: {error}\n')


if __name__ == '__main__':
    main()
