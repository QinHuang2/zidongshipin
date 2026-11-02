# 字幕纸上视频 · srt-paper-video

一个可安装的 Codex skill：把 SRT 字幕转成按叙事顺序勾线、上色的纸张手绘 MP4。适合知识讲解、课程和口播配图。

## 安装与调用

下载或克隆本仓库，将整个文件夹放到 `~/.codex/skills/srt-paper-video/`，确保 `SKILL.md` 就在此目录下。重新打开 Codex 后可调用：

> 使用 $srt-paper-video，把这份 SRT 制作成手绘解说视频，旁白使用 narration.wav。

依赖 Python 3.10+ 与系统 FFmpeg（含 ffprobe）。先进入 skill 目录，再创建隔离环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/self_test.py
```

Windows 使用 `.venv\Scripts\python.exe`。请自行按系统安装 FFmpeg；脚本不自动修改系统环境。首次准备环境可能需要联网。

## 能力与边界

- 严格解析 SRT，并生成保持原始时间轴的建议分幕。
- 由 AI 理解字幕、规划分镜、调用可用生图工具、进行像素区域标注。
- 本地 HTML 编辑器：区域拖动、JSON 编辑、时序代理、下载标注。
- Python 渲染：按实际深色像素扫描勾线，随后逐行添彩；内置简笔画笔尖。
- 多幕合成；可合入用户已有旁白音轨。无音频则输出静音视频。
- 不包含生图模型、TTS 服务、自动人物表演或自动烧录字幕。

“字幕驱动”指 AI 按语义建立区域和时间关联；解析器本身不理解语义。默认建议 30 秒分幕，AI 仍需审核。渲染是位图的笔迹揭示，不是真实画师的语义笔顺；短笔迹之间会抬笔，添彩为扫描效果。最终效果依赖配图和标注质量。

## 命令

在 skill 目录中，使用虚拟环境 Python 执行：

```bash
python scripts/paper_video.py plan examples/demo.srt /path/to/project/plan.json
python scripts/paper_video.py init /path/to/project/scene-01.png /path/to/project/scene-01.json --duration-ms 3000
# 实际查看配图，按字幕拆分标注；打开 assets/editor.html 调整并下载 JSON
python scripts/paper_video.py validate /path/to/project/scene-01.png /path/to/project/scene-01.json
python scripts/paper_video.py render /path/to/project/scene-01.png /path/to/project/scene-01.json /path/to/project/scene-01.mp4
# 为 plan.json 每幕添加 video 路径后合成
python scripts/paper_video.py assemble /path/to/project/plan.json /path/to/project/final.mp4 --audio /path/to/narration.wav
```

`python` 在以上示例中指隔离环境解释器。原图使用均匀暖米黄背景 `#F5EBD7`；默认输出宽 1280，24fps，画幅随源图。每幕结尾至少 500ms；合成音频从 0 起对齐，长音频裁到视频时长，短音频补静音。不要用静音填补掩盖缺失旁白。

完整工作流程见 [SKILL.md](SKILL.md)，字段说明见 [标注格式](references/annotation.md)。

## 验证

`self_test.py` 创建临时几何图并实际渲染，检查首帧、未开始区域隐藏、收尾源图还原、时长、非法标注拒绝，以及多幕音轨合成。生成文件留在指定 `--output` 目录，默认系统临时目录。测试图是技术样例，不代表 AI 配图美术效果。

## 来源

工作流思路参考 [geeklee/srt-whiteboard-animation](https://github.com/geeklee/srt-whiteboard-animation)：字幕分镜、语义区域、遮罩保护、渐进绘制。当前 Python 代码、编辑器与说明独立编写，未复制其实现或手部素材。两者不是同一个项目，渲染方法和标注格式不兼容。MIT 许可见 [LICENSE](LICENSE)。
