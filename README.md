# googleart-download

下载 Google Arts & Culture 作品页里的高清图片。程序会解析页面里的瓦片元数据，下载所有瓦片并自动拼接成一张完整图片。

现在支持：

- 下载时日志输出
- 瓦片和批次进度条
- `--tui` 实时终端面板
- 多个 URL 批量下载
- `--url-file` 从文件读取 URL

## 安装

```bash
uv sync
```

推荐直接用项目脚本：

```bash
uv run googleart-download --help
```

## 用法

```bash
uv run googleart-download "https://artsandculture.google.com/asset/recto-the-fetus-in-the-womb-verso-notes-on-reproduction-with-sketches-of-a-fetus-in-utero-etc-leonardo-da-vinci/qgFUAw5Zc1wsbw" -o downloads
```

也可以指定输出文件名：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/recto-the-fetus-in-the-womb-verso-notes-on-reproduction-with-sketches-of-a-fetus-in-utero-etc-leonardo-da-vinci/qgFUAw5Zc1wsbw" -o downloads -f fetus.jpg
```

批量下载：

```bash
uv run googleart-download \
  "https://artsandculture.google.com/asset/recto-the-fetus-in-the-womb-verso-notes-on-reproduction-with-sketches-of-a-fetus-in-utero-etc-leonardo-da-vinci/qgFUAw5Zc1wsbw" \
  "https://artsandculture.google.com/asset/taj-mahal/7QHkbH1IgneKLA" \
  --tui \
  --log-file logs/run.log
```

从文件读取：

```bash
uv run googleart-download --url-file urls.txt --tui
```

## 说明

- 需要完整的作品页 URL。你给的示例链接少了最后的作品 ID，正确格式通常是 `/asset/<slug>/<assetId>`。
- 程序当前面向单张作品页，不处理整个合集或故事页。
- 有些页面可能会被地区、权限或站点改版影响，如果 Google 改了瓦片签名规则，代码也需要跟着调整。
- 目前的 TUI 是基于 `rich` 的 live dashboard，不是复杂的全屏交互应用。这是有意为之，因为当前任务流是单向下载任务，`rich` 方案更稳、更容易维护。
- 包代码现在采用 `src/` 目录布局。根目录的 [main.py](/home/chao/code/googleart-download/main.py) 只是兼容入口。
