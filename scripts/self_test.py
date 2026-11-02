#!/usr/bin/env python3
"""Observable end-to-end tests. No network or image-generation credits needed."""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import tempfile

import numpy as np
from PIL import Image, ImageDraw

import paper_video as pv


def frame(path, seconds):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(seconds), '-i', str(path),
                          '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(180, 320, 3)


def probe(path):
    return json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format',
                                     '-of', 'json', str(path)], capture_output=True,
                                    text=True, check=True).stdout)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = args.output or Path(tempfile.mkdtemp(prefix='paper-video-'))
    root.mkdir(parents=True, exist_ok=True)
    image = Image.new('RGB', (320, 180), pv.BG)
    d = ImageDraw.Draw(image)
    d.ellipse((25, 35, 110, 125), outline=(55, 55, 55), width=4)
    d.rectangle((200, 45, 280, 130), outline=(55, 55, 55), fill=(220, 105, 65), width=4)
    source = root / 'source.png'
    image.save(source)
    ann = dict(version=1, canvas=[320, 180], durationMs=3000, elements=[
        dict(id='circle', subtitle='先画圆', region=[10, 10, 140, 150], startMs=0, endMs=1000, protected=[]),
        dict(id='square', subtitle='再画方', region=[180, 10, 130, 150], startMs=1200, endMs=2500, protected=[])])
    pv.write_json(root / 'source.json', ann)
    pv.validate(source, ann)
    for mutate in ['overlap', 'bounds', 'tail', 'canvas']:
        bad = copy.deepcopy(ann)
        if mutate == 'overlap': bad['elements'][1]['startMs'] = 500
        if mutate == 'bounds': bad['elements'][0]['region'][0] = -1
        if mutate == 'tail': bad['elements'][1]['endMs'] = 2900
        if mutate == 'canvas': bad['canvas'] = [1, 1]
        try:
            pv.validate(source, bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f'未拒绝非法标注: {mutate}')
    srt = root / 'gaps.srt'
    srt.write_text('1\n00:00:00,200 --> 00:00:01,000\n第一幕。\n\n2\n00:00:02,000 --> 00:00:02,500\n第二幕。\n', encoding='utf-8-sig')
    pv.plan(srt, root / 'timing.json', 1)
    timing = pv.read_json(root / 'timing.json')
    assert [(s['startMs'], s['endMs']) for s in timing['scenes']] == [(0, 2000), (2000, 3000)]
    assert timing['scenes'][0]['cues'][0]['localStartMs'] == 200
    srt.write_text('1\n00:00:01,000 --> 00:00:00,500\n倒置\n', encoding='utf-8')
    try:
        pv.parse_srt(srt)
    except ValueError:
        pass
    else:
        raise AssertionError('未拒绝倒置字幕')
    video = root / 'scene.mp4'
    pv.render(source, ann, video, fps=12, width=320)
    first, middle, end = frame(video, 0), frame(video, .75), frame(video, 2.8)
    bg = np.array(pv.BG)
    assert np.abs(first.astype(int) - bg).mean() < 3, '首帧不是干净背景'
    assert np.abs(middle[40:135, 195:285].astype(int) - bg).mean() < 3, '后续模块提前露出'
    assert np.abs(middle[30:130, 20:115].astype(int) - bg).mean() > 3, '首模块未绘制'
    assert np.abs(end.astype(int) - np.array(image)).mean() < 4, '结尾未还原原图'
    info = probe(video)
    assert abs(float(info['format']['duration']) - 3) < .09
    # Overlapping rectangles: later content must remain hidden during first draw.
    overlapping = copy.deepcopy(ann)
    overlapping['elements'][0]['region'] = [10, 10, 300, 150]
    overlap_video = root / 'overlap.mp4'
    pv.render(source, overlapping, overlap_video, fps=12, width=320)
    overlap_middle = frame(overlap_video, .75)
    assert np.abs(overlap_middle[40:135, 195:285].astype(int) - bg).mean() < 3, '重叠区保护失败'
    assert np.abs(frame(overlap_video, 2.8).astype(int) - np.array(image)).mean() < 4
    missing = copy.deepcopy(ann)
    missing['elements'] = missing['elements'][:1]
    try:
        pv.render(source, missing, root / 'missing.mp4', fps=12, width=320)
    except ValueError:
        pass
    else:
        raise AssertionError('未拒绝漏标内容')
    audio = root / 'tone.wav'
    subprocess.run(['ffmpeg', '-v', 'error', '-n', '-f', 'lavfi', '-i',
                    'sine=frequency=440:duration=5', str(audio)], check=True)
    pv.write_json(root / 'assembly.json', dict(scenes=[
        dict(startMs=0, endMs=3000, video='scene.mp4'),
        dict(startMs=3000, endMs=6000, video='overlap.mp4')]))
    final = root / 'final.mp4'
    pv.assemble(root / 'assembly.json', final, audio)
    result = probe(final)
    assert {s['codec_type'] for s in result['streams']} == {'video', 'audio'}
    assert abs(float(result['format']['duration']) - 6) < .1
    for name, pixels in [('first', first), ('middle', middle), ('end', end)]:
        Image.fromarray(pixels).save(root / f'{name}.png')
    report = dict(status='passed', checks=['invalid-annotations', 'srt-timing-and-gaps',
                  'invalid-srt', 'clean-first-frame', 'future-region-hidden',
                  'ink-visible', 'final-image-restored', 'overlap-protection',
                  'uncovered-content-rejected', 'two-scene-duration', 'audio-track-and-padding'],
                  output=str(root.resolve()))
    pv.write_json(root / 'report.json', report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
