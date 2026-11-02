# 标注格式 v1

`canvas` 是源图 `[宽,高]`，所有区域用源图整数像素 `[x,y,宽,高]`。元素数组顺序就是绘制顺序，无单独 sequence。时间单位毫秒，相对本幕零点；元素必须串行，最后结束不晚于 `durationMs - 500`。

```json
{
  "version": 1,
  "canvas": [1280, 720],
  "durationMs": 3000,
  "elements": [
    {"id":"first", "label":"提出问题", "subtitle":"先提出一个问题。", "region":[50,100,400,400], "startMs":0, "endMs":1200, "protected":[]},
    {"id":"second", "label":"给出答案", "subtitle":"再找到对应答案。", "region":[700,100,400,400], "startMs":1200, "endMs":2500, "protected":[]}
  ]
}
```

允许掩码 = 本元素 region 减去所有后续元素 region，再减去本元素 protected。保护区中需要保留的可见内容必须由后续元素接管。矩形重叠可能延迟背景部分的出现；源图尽量分离对象。渲染器拒绝存在明显未覆盖内容的标注。

背景约定为均匀 `#F5EBD7`，建议无纸纹，避免整张纹理都被当作画面内容。画面内容最终还原源图像素，不是模型生成动作。笔尖是程序绘制的简笔画笔，没有使用第三方真人手部图片。

plan.json 中 `scenes[].startMs/endMs` 为绝对时间，`cues[].localStartMs/localEndMs` 为本幕局部时间。每幕 `durationMs=endMs-startMs`；首幕从 0 起，幕间无缝。首段字幕前的静音包含在首幕，幕间字幕空隙包含在前幕，最后增加 500ms 收尾。合成时所有单幕使用同样分辨率、比例和帧率，`video` 为相对 plan.json 的路径。

编辑器：图片加载会清空旧标注；先载图片再载 JSON。拖动只移动区域，不缩放；大小与重排在右侧 JSON 修改。应用校验后下载文件；浏览器可能添加重名后缀，运行渲染前确认使用的是最新文件。
