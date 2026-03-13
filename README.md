# googleart-download

下载 Google Arts & Culture 作品页里的高清图片。程序会解析页面里的瓦片元数据，下载所有瓦片并自动拼接成一张完整图片。

现在支持：

- 下载时日志输出
- 瓦片和批次进度条
- `--tui` 实时终端面板
- 多个 URL 批量下载
- `--url-file` 从文件读取 URL
- 页面、元数据、瓦片请求自动重试
- 批量任务状态跟踪和失败汇总
- 用户友好的尺寸选择：`--size` / `--max-dimension`
- 先查看可选尺寸：`--list-sizes`
- 已存在文件默认跳过
- 单作品 tile 缓存和中断后自动复用
- 超大图拼接前的内存风险保护
- 可选 `pyvips` 大图拼接后端
- 可选将作品元数据写入 JPEG EXIF
- 可选输出同名 JSON sidecar 元数据文件
- 失败作品可按批次轮次重跑

## 安装

```bash
uv sync
```

如果你需要更稳地处理超大图，安装大图拼接增强依赖：

```bash
uv sync --extra large-images
```

`pyvips` 还需要系统里的 `libvips`：

- macOS: `brew install vips`
- Debian/Ubuntu: `sudo apt install libvips libvips-dev`
- Fedora: `sudo dnf install vips vips-devel`
- Windows: 安装 `libvips` 发行包并把其 `bin` 目录加入 `PATH`

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

重试参数：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --retries 5 --retry-backoff 1.0
```

失败作品按批次再跑一轮：

```bash
uv run googleart-download --url-file urls.txt --rerun-failures 1
```

先查看这张作品有哪些可选尺寸：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --list-sizes
```

按用户友好的预设尺寸下载：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --size preview
uv run googleart-download "https://artsandculture.google.com/asset/..." --size medium
uv run googleart-download "https://artsandculture.google.com/asset/..." --size large
uv run googleart-download "https://artsandculture.google.com/asset/..." --size max
```

按最长边限制下载：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --max-dimension 8000
```

批量失败时继续处理后续任务：

```bash
uv run googleart-download --url-file urls.txt
```

批量失败时立刻停止：

```bash
uv run googleart-download --url-file urls.txt --fail-fast
```

默认会跳过已经存在的目标文件。如果你需要强制重新下载：

```bash
uv run googleart-download --url-file urls.txt --no-skip-existing
```

默认不会修改图片 EXIF。如果你需要把作品信息写入输出 JPEG：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --write-metadata
```

如果你需要结构化元数据文件：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --write-sidecar
```

如果你两者都要：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --write-metadata --write-sidecar
```

控制拼图后端：

```bash
uv run googleart-download "https://artsandculture.google.com/asset/..." --stitch-backend auto
uv run googleart-download "https://artsandculture.google.com/asset/..." --stitch-backend pillow
uv run googleart-download "https://artsandculture.google.com/asset/..." --stitch-backend pyvips
```

## 说明

- 需要完整的作品页 URL。你给的示例链接少了最后的作品 ID，正确格式通常是 `/asset/<slug>/<assetId>`。
- 程序当前面向单张作品页，不处理整个合集或故事页。
- 下载时会把单张作品的 tile 临时缓存到输出目录下的 `.googleart-cache/`。如果下载过程中中断，下次运行会自动复用已经完成的 tile。
- 单张作品成功写出后，会默认清理对应的 tile 缓存；失败时缓存会保留，便于恢复。
- `--size` 是用户友好的语义化尺寸预设；`--max-dimension` 则允许你直接控制最长边上限。
- 默认仍然是 `--size max`，也就是下载当前可用的最大尺寸。
- `--list-sizes` 不会开始下载图片，只会读取页面和瓦片元数据，列出当前作品可选的层级尺寸和 tile 数。
- `--stitch-backend auto` 会优先使用 Pillow；当图像过大、不适合安全内存拼接时，会切到 `pyvips`。
- 如果系统没有可用的 `pyvips/libvips`，超大图会明确报错并提示安装，而不是继续把机器顶死。
- 当前 `pyvips` 路径还不支持写 JPEG EXIF。超大图场景下如果需要元数据，优先使用 `--write-sidecar`。
- 有些页面可能会被地区、权限或站点改版影响，如果 Google 改了瓦片签名规则，代码也需要跟着调整。
- 目前的 TUI 是基于 `rich` 的 live dashboard，不是复杂的全屏交互应用。这是有意为之，因为当前任务流是单向下载任务，`rich` 方案更稳、更容易维护。
- 包代码现在采用 `src/` 目录布局。根目录的 [main.py](/home/chao/code/googleart-download/main.py) 只是兼容入口。
