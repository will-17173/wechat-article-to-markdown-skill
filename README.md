# WeChat Article to Markdown

从微信公众号文章链接一键生成结构化 Markdown 文档与本地图片资源。

## 功能特性

- 一键抓取微信公众文章并转换为 Markdown
- 自动下载正文图片到本地
- 智能清理公众号噪音内容（如"预览时标签不可点"、"继续滑动看下一个"等）
- 规范化标题层级和 Markdown 格式
- 自动编号输出目录，便于管理多篇文章
- 纯 Python 实现，仅依赖 `requests`

## 安装

```bash
# 克隆仓库
git clone git@github.com:will-17173/wechat-article-to-markdown-skill.git
cd wechat-article-to-markdown-skill

# 安装依赖
pip install requests
```

## 使用方法

### 命令行

```bash
python scripts/wechat_article_pipeline.py <微信文章链接>
```

### 示例

```bash
# 基本用法
python scripts/wechat_article_pipeline.py "https://mp.weixin.qq.com/s/xxxxxx"

# 指定输出目录
python scripts/wechat_article_pipeline.py "https://mp.weixin.qq.com/s/xxxxxx" --output-dir "./my-articles"

# 同时保存清洗后的 HTML
python scripts/wechat_article_pipeline.py "https://mp.weixin.qq.com/s/xxxxxx" --save-html
```

### 参数说明

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `url` | 微信文章链接（必填） | - |
| `--output-dir` | 输出根目录 | `{工作区}/articles` |
| `--workspace-dir` | 工作区目录 | 自动检测 |
| `--save-html` | 额外保存清洗后的 HTML 文件 | 否 |
| `--timeout` | 网络请求超时秒数 | 30 |

### 工作区检测

脚本会按以下优先级检测工作区目录：

1. `--workspace-dir` 参数
2. 环境变量 `WORKSPACE_DIR`
3. 环境变量 `PROJECT_ROOT`
4. 环境变量 `CLAUDE_WORKSPACE`
5. 当前工作目录

## 输出结构

```
articles/
├── 01_文章标题/
│   ├── 文章标题.md
│   ├── source.html          # 使用 --save-html 时生成
│   ├── image_01.jpg
│   ├── image_02.png
│   └── ...
├── 02_另一篇文章/
│   ├── 另一篇文章.md
│   └── ...
```

- 目录自动按序号递增（01_、02_、03_...）
- Markdown 文件名与目录标题保持一致
- 图片自动命名为 `image_01.jpg`、`image_02.png` 等

## 处理流程

1. 请求微信文章页面
2. 提取标题、作者、公众号名称和正文区域
3. 修复微信文章懒加载图片地址
4. 下载正文图片到本地输出目录
5. 将正文转换为 Markdown
6. 清理格式：
   - 移除重复标题
   - 规范标题层级（避免跳级）
   - 清理无效链接
   - 删除缺失图片引用
   - 移除公众号噪音内容
   - 规范空行

## 作为 Claude Code Skill 使用

本项目可作为 [Claude Code](https://github.com/anthropics/claude-code) 的 skill 使用：

```bash
npx skills add will-17173/wechat-article-to-markdown-skill
```

## 注意事项

- 仅支持 `mp.weixin.qq.com` 或 `weixin.qq.com` 域名的文章
- 若文章受限、被删除或需要登录，抓取会失败
- 部分图片可能因防盗链等原因下载失败，脚本会自动跳过

## 依赖

- Python 3.9+
- [requests](https://requests.readthedocs.io/)

## License

MIT