---
name: srt-paper-video
description: 将 SRT 字幕制作成按叙事顺序逐步勾线和上色的纸张手绘 MP4，支持分镜、配图、区域标注、编辑预览及合入已有旁白。适用于科普、课程和口播解说的手绘视频，不用于角色连续表演动画。
---

# 字幕纸上视频

把字幕内容变成极简插图，并让插图主体跟随叙事逐步绘出。使用本 skill 自带 Python 渲染器；所有命令相对本 skill 目录。面向用户用中文。

## 输入与决策

必需：SRT 或已获用户同意制作的时间轴，以及输出目录。可选：已有插图、旁白音频、画幅、风格。SRT 不含音频；无音频时交付静音视频并明确说明。不要假称具备自动配音或角色动作生成。

检查用户已有约束。未指定时采用 16:9、暖米黄背景 `#F5EBD7`、深灰线条与少量红橙蓝点缀，默认输出宽 1280、24fps。若用户要其他画幅，按要求生成源图；渲染保持源图比例。

默认先展示分镜和一幕样片确认风格，再扩展全片。用户明确要求全程直接完成时，在授权范围内连续执行。用户只要求策略或预览时止于对应阶段，不扩大生成范围。

## 执行

1. 准备环境：在项目工作目录创建虚拟环境，安装本目录 `requirements.txt`；检查 `ffmpeg` 与 `ffprobe`。不修改全局 Python。生成资产和中间文件留在用户项目内。
2. 用 `scripts/paper_video.py plan input.srt project/plan.json` 解析字幕。解析器严格拒绝重叠、倒置或空字幕。30 秒是建议上限，长字幕不强拆，语义分镜需由你复核。每幕只表达一个核心概念，填写 `coreIdea` 和 `imagePrompt`，保留场景绝对起止时间及局部字幕时间。调整分幕时同步更新 cues 与局部时间，保证全片时间连续。
3. 使用当前环境实际可用的生图工具生成每幕插图；工具不可用时索取已有配图或报告缺失，不能用占位图冒充正式交付。统一线条、人物与配色，主体分离、留白充分。默认不在场景中生成文字。已有配图必须实际查看、读取像素尺寸后再标注。生图涉及费用或额度时遵循用户已有授权与工具要求。
4. 创建区域标注：先读对应字幕事件，再按主体/动作含义安排元素数组顺序。运行 `init` 可生成结构模板，但必须替换占位说明并拆分实际区域。详细格式见 [references/annotation.md](references/annotation.md)。同一支笔串行绘制，所有元素结束后保留至少 500ms。不要随意拉长单幕造成旁白漂移；应在原字幕跨度内分配，必要时减少元素或加快绘制。
5. 打开 `assets/editor.html`，加载图片和标注；可拖动区域，编辑 JSON 中大小、时间、字幕和顺序，下载后保存回项目目录。矩形时序代理不代表真实笔迹，最终效果以 MP4 为准。编辑器不自动写回文件，必须校验实际保存的 JSON。
6. 执行 `validate`，再 `render`。渲染器按深色像素生成蛇形短笔迹，2/3 时间勾线、1/3 时间按行添彩；不等同真实画师的语义笔顺。后绘区域和保护区在开始前不可见。区域未覆盖画面内容时修正标注，不依赖结尾突然露出全图。
7. 单幕验证后在 plan 中为每幕添加 `video` 路径（相对 plan.json），执行 `assemble plan.json final.mp4 [--audio narration.wav]`。音频从全片零点起合入，短音频补静音，长音频截到全片时长；合成前检查音频与 SRT 是否同源、同起点，不能把补静音当作配音完整。

```bash
python scripts/paper_video.py init project/scene-01.png project/scene-01.json --duration-ms 30000
python scripts/paper_video.py validate project/scene-01.png project/scene-01.json
python scripts/paper_video.py render project/scene-01.png project/scene-01.json project/scene-01.mp4 --width 1280 --fps 24
python scripts/paper_video.py assemble project/plan.json project/final.mp4 --audio project/narration.wav
```

## 验收与交付

检查首帧背景干净、每个元素出场符合字幕、中段不提前露出后续内容、结尾完整且至少停留 500ms。用 ffprobe 验证尺寸、时长和音轨，有音频时实际听看同步。静态抽帧不能冒充完整视听验收。渲染器输出文件已存在时拒绝覆盖，修改时使用新版本文件名。

交付成片、分镜 JSON、原图、标注和必要说明；明确静音/有声、真实验证范围、剩余问题。示例自检可执行 `python scripts/self_test.py`，它使用程序绘制的几何测试图，只验证渲染逻辑，不能替代正式内容生图与人工验收。
