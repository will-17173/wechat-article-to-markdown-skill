---
name: wechat-article-pipeline
description: 从微信公众文章链接直接生成结构化 Markdown 文档与本地图片资源。适用于需要一键完成抓取、转换、图片下载和 Markdown 格式清理的场景，可独立迁移到其它项目使用。
---

# WeChat Article Pipeline

一个自包含的工作流 skill：输入微信文章链接，输出整理后的 Markdown 文章目录。

## 使用场景

- 用户提供了 mp.weixin.qq.com 文章链接
- 需要直接产出 Markdown，不想再手动串联多个 skill
- 需要把技能复制到别的项目或分享给别人使用

## 使用方法

```bash
python scripts/wechat_article_pipeline.py <wechat_article_url> [--output-dir <目录>] [--save-html]
```

## 示例

```bash
python scripts/wechat_article_pipeline.py "https://mp.weixin.qq.com/s/xxxxxx" --output-dir "./articles"
```

如需同时保留抓取后的清洗版 HTML：

```bash
python scripts/wechat_article_pipeline.py "https://mp.weixin.qq.com/s/xxxxxx" --output-dir "./articles" --save-html
```

## 工作流

执行时按以下步骤完成：

1. 请求微信文章页面
2. 提取标题、作者、公众号名称和正文区域
3. 修复微信文章懒加载图片地址
4. 下载正文图片到本地输出目录
5. 将正文转换为 Markdown
6. 先执行脚本内置的 Markdown formatter，清理标题、空行、无效链接、缺失图片和公众号噪音内容
7. 如果当前环境存在 markdown-formatter skill，再对生成的 Markdown 自动执行一次 markdown-formatter 规则清理
8. 输出文章目录、Markdown 路径和处理摘要

## 输出结构

```text
articles/
├── 01_文章标题/
│   ├── 文章标题.md
│   ├── source.html
│   ├── image_01.jpg
│   ├── image_02.png
│   └── ...
```

说明：

- 目录自动按序号递增，例如 01_、02_、03_
- Markdown 文件名与目录标题保持一致
- 使用 --save-html 时才会额外输出 source.html

## 参数

- `<wechat_article_url>`：微信文章链接
- `--output-dir`：输出目录，默认使用当前目录下的 articles
- `--save-html`：是否保存清洗后的 HTML 文件
- `--timeout`：请求超时秒数，默认 30

## 依赖

- Python 3.9+
- requests

安装依赖：

```bash
pip install requests
```

## 输出摘要

脚本完成后会输出：

- 文章标题
- 作者与公众号信息
- 输出目录
- Markdown 文件路径
- 下载图片数量
- 格式化修改摘要

## 注意事项

- 该 skill 为独立实现，不依赖其它 skill
- 若当前项目里存在 markdown-formatter skill，使用本 skill 时应在脚本生成 Markdown 后自动补一遍 markdown-formatter
- 主要面向微信公众文章页面结构，普通网页不保证完全适配
- 若文章受限、被删除或需要登录，抓取会失败
- Markdown 会直接写入输出目录中的目标文件