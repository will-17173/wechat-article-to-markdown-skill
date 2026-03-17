#!/usr/bin/env python3
"""
Self-contained WeChat article pipeline.

Fetch a WeChat public article, extract the main content, download images,
convert the content to Markdown, format the Markdown, and save the final
article bundle to a numbered output folder.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

import requests


USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

INVALID_LINK_PATTERNS = (
    "javascript:",
    "#",
)

WECHAT_NOISE_PATTERNS = [
    re.compile(r"^预览时标签不可点$"),
    re.compile(r"^继续滑动看下一个$"),
    re.compile(r"^微信扫一扫关注该公众号$"),
    re.compile(r"^轻触阅读原文$"),
    re.compile(r"^原创.*在小说阅读器中沉浸阅读$"),
    re.compile(r"^以下文章来源于.*$"),
    re.compile(r"^作者 \| .*$"),
]


@dataclass
class ArticleData:
    title: str
    author: str
    account_name: str
    content_html: str
    original_url: str


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', '_', name)
    name = re.sub(r'_+', '_', name).strip('_')
    return (name[:100] or 'untitled').strip('_') or 'untitled'


def get_next_folder_number(base_dir: Path) -> int:
    if not base_dir.exists():
        return 1

    max_num = 0
    for child in base_dir.iterdir():
        if not child.is_dir():
            continue
        match = re.match(r'^(\d+)_', child.name)
        if match:
            max_num = max(max_num, int(match.group(1)))
    return max_num + 1


def strip_tags(value: str) -> str:
    value = re.sub(r'<[^>]+>', '', value)
    return html.unescape(value).strip()


def normalize_inline_text(value: str) -> str:
    value = value.replace('\xa0', ' ')
    value = re.sub(r'\s+', ' ', value)
    return value.strip()


class WeChatArticlePipeline:
    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(self._build_headers())

    def _build_headers(self) -> Dict[str, str]:
        return {
            'User-Agent': USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'Upgrade-Insecure-Requests': '1',
        }

    def validate_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in {'http', 'https'} and (
            'mp.weixin.qq.com' in parsed.netloc or 'weixin.qq.com' in parsed.netloc
        )

    def fetch_html(self, url: str) -> str:
        response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        response.raise_for_status()
        if response.encoding in (None, 'ISO-8859-1'):
            response.encoding = 'utf-8'
        return response.text

    def extract_article(self, source_html: str, original_url: str) -> ArticleData:
        title = self._extract_first_match(
            source_html,
            [
                r'id="activity-name"[^>]*>\s*<span[^>]*>(.*?)</span>',
                r'class="rich_media_title[^"]*"[^>]*>(.*?)</h1>',
                r'<h1[^>]*>(.*?)</h1>',
                r'<title>(.*?)</title>',
            ],
        ) or '未命名文章'

        author = self._extract_first_match(
            source_html,
            [
                r'id="js_name"[^>]*>(.*?)</a>',
                r'class="profile_nickname[^"]*"[^>]*>(.*?)</span>',
            ],
        ) or ''

        account_name = self._extract_first_match(
            source_html,
            [
                r'class="profile_nickname[^"]*"[^>]*>(.*?)</span>',
                r'id="js_name"[^>]*>(.*?)</a>',
            ],
        ) or ''

        content_html = self._extract_content_html(source_html)
        content_html = self._clean_html(content_html)

        return ArticleData(
            title=title,
            author=author,
            account_name=account_name,
            content_html=content_html,
            original_url=original_url,
        )

    def _extract_first_match(self, content: str, patterns: List[str]) -> str:
        for pattern in patterns:
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                value = strip_tags(match.group(1))
                value = re.sub(r'\s*[-_|]\s*微信.*$', '', value)
                if value:
                    return value
        return ''

    def _extract_content_html(self, source_html: str) -> str:
        patterns = [
            r'id="img-content"[^>]*>(.*?)<div[^>]*id="js_pc_qr_code"',
            r'id="js_content"[^>]*>(.*?)</div>\s*</div>\s*<div[^>]*class="rich_media_tool',
            r'id="img-content"[^>]*>(.*?)$',
            r'<body[^>]*>(.*?)</body>',
        ]
        for pattern in patterns:
            match = re.search(pattern, source_html, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1)
        return source_html

    def _clean_html(self, content_html: str) -> str:
        content_html = re.sub(
            r'<script[^>]*>.*?</script>',
            '',
            content_html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        content_html = re.sub(
            r'<style[^>]*>.*?</style>',
            '',
            content_html,
            flags=re.DOTALL | re.IGNORECASE,
        )
        content_html = re.sub(r'<!--.*?-->', '', content_html, flags=re.DOTALL)

        def replace_lazy_image(match: re.Match[str]) -> str:
            image_tag = match.group(0)
            source_match = re.search(
                r'(?:data-src|data-original|src)=["\']([^"\']+)["\']',
                image_tag,
                flags=re.IGNORECASE,
            )
            if not source_match:
                return image_tag
            src = html.unescape(source_match.group(1))
            if ' src=' in image_tag:
                image_tag = re.sub(r'src=["\'][^"\']+["\']', f'src="{src}"', image_tag, count=1)
            else:
                image_tag = re.sub(r'<img', f'<img src="{src}"', image_tag, count=1)
            return image_tag

        content_html = re.sub(r'<img[^>]*>', replace_lazy_image, content_html, flags=re.IGNORECASE)
        content_html = re.sub(
            r'<img[^>]*(?:height=["\']?1["\']?[^>]*width=["\']?1["\']?|width=["\']?1["\']?[^>]*height=["\']?1["\']?)[^>]*>',
            '',
            content_html,
            flags=re.IGNORECASE,
        )
        content_html = re.sub(r'<div[^>]*>\s*</div>', '', content_html, flags=re.IGNORECASE)
        content_html = re.sub(r'\n\s*\n\s*\n+', '\n\n', content_html)
        return content_html.strip()

    def build_clean_html(self, article: ArticleData) -> str:
        meta_parts = []
        if article.author:
            meta_parts.append(f'<span>作者: {html.escape(article.author)}</span>')
        if article.account_name:
            meta_parts.append(f'<span>公众号: {html.escape(article.account_name)}</span>')
        meta_html = ' | '.join(meta_parts)

        return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(article.title)}</title>
</head>
<body>
    <article>
        <h1>{html.escape(article.title)}</h1>
        <p>{meta_html}</p>
        <div class="article-content">
{article.content_html}
        </div>
        <p>原文链接: <a href="{html.escape(article.original_url)}">{html.escape(article.original_url)}</a></p>
    </article>
</body>
</html>
'''


class MarkdownImageDownloader:
    def __init__(self, output_dir: Path, base_url: Optional[str], timeout: int) -> None:
        self.output_dir = output_dir
        self.base_url = base_url
        self.timeout = timeout
        self.image_index = 0

    def download(self, source: str) -> Optional[str]:
        source = html.unescape(source).split('#', 1)[0]
        if not source or source.startswith('data:'):
            return None

        if self.base_url and not source.startswith(('http://', 'https://')):
            source = urljoin(self.base_url, source)

        self.image_index += 1
        extension = self._detect_extension(source)
        file_name = f'image_{self.image_index:02d}{extension}'
        file_path = self.output_dir / file_name

        headers = {
            'User-Agent': USER_AGENT,
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        if 'mmbiz.qpic.cn' in source or 'weixin' in source:
            headers['Referer'] = 'https://mp.weixin.qq.com/'
            headers['Origin'] = 'https://mp.weixin.qq.com'

        try:
            response = requests.get(source, headers=headers, timeout=self.timeout, stream=True)
            response.raise_for_status()
            with file_path.open('wb') as file_handle:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        file_handle.write(chunk)
            if file_path.stat().st_size < 100:
                file_path.unlink(missing_ok=True)
                return None
            return file_name
        except requests.RequestException:
            file_path.unlink(missing_ok=True)
            return None

    def _detect_extension(self, source: str) -> str:
        parsed = urlparse(source)
        query = parsed.query.lower()
        for fmt, extension in [
            ('png', '.png'),
            ('gif', '.gif'),
            ('webp', '.webp'),
            ('jpeg', '.jpg'),
            ('jpg', '.jpg'),
        ]:
            if f'wx_fmt={fmt}' in query:
                return extension

        lower_path = parsed.path.lower()
        for extension in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'):
            if lower_path.endswith(extension):
                return extension if extension != '.jpeg' else '.jpg'
        return '.jpg'


class HTMLToMarkdownParser(HTMLParser):
    def __init__(self, image_downloader: MarkdownImageDownloader) -> None:
        super().__init__()
        self.image_downloader = image_downloader
        self.result: List[str] = []
        self.tag_stack: List[str] = []
        self.list_stack: List[str] = []
        self.list_counters: List[int] = []
        self.ignore_tags = {'script', 'style', 'nav', 'footer', 'header', 'aside'}
        self.skip_depth = 0
        self.current_href: Optional[str] = None
        self.pending_newlines = 0
        self.in_pre = False

    def add_newlines(self, count: int) -> None:
        self.pending_newlines = max(self.pending_newlines, count)

    def flush_newlines(self) -> None:
        if self.pending_newlines > 0:
            self.result.append('\n' * self.pending_newlines)
            self.pending_newlines = 0

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        attrs_dict = {key: value or '' for key, value in attrs}

        if tag in self.ignore_tags:
            self.skip_depth += 1
            return
        if self.skip_depth > 0:
            return

        self.tag_stack.append(tag)
        if tag in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            self.add_newlines(2)
            self.flush_newlines()
            level = int(tag[1])
            self.result.append('#' * level + ' ')
        elif tag == 'p':
            self.add_newlines(2)
            self.flush_newlines()
        elif tag == 'br':
            self.result.append('  \n')
        elif tag == 'hr':
            self.flush_newlines()
            self.result.append('\n---\n')
        elif tag in {'strong', 'b'}:
            self.result.append('**')
        elif tag in {'em', 'i'}:
            self.result.append('*')
        elif tag == 'code' and not self.in_pre:
            self.result.append('`')
        elif tag == 'pre':
            self.add_newlines(2)
            self.flush_newlines()
            self.result.append('```text\n')
            self.in_pre = True
        elif tag == 'blockquote':
            self.add_newlines(2)
            self.flush_newlines()
            self.result.append('> ')
        elif tag == 'a':
            self.current_href = attrs_dict.get('href', '').strip()
            self.result.append('[')
        elif tag == 'img':
            self.flush_newlines()
            source = (
                attrs_dict.get('data-src')
                or attrs_dict.get('data-original')
                or attrs_dict.get('src')
                or ''
            )
            alt_text = attrs_dict.get('alt') or attrs_dict.get('data-alt') or 'image'
            local_path = self.image_downloader.download(source)
            target = local_path or source
            if target:
                self.result.append(f'![{alt_text}]({target})')
                self.add_newlines(2)
        elif tag == 'ul':
            self.add_newlines(2)
            self.flush_newlines()
            self.list_stack.append('ul')
        elif tag == 'ol':
            self.add_newlines(2)
            self.flush_newlines()
            self.list_stack.append('ol')
            self.list_counters.append(1)
        elif tag == 'li':
            self.flush_newlines()
            indent = '  ' * max(0, len(self.list_stack) - 1)
            if self.list_stack and self.list_stack[-1] == 'ol':
                index = self.list_counters[-1]
                self.result.append(f'{indent}{index}. ')
                self.list_counters[-1] += 1
            else:
                self.result.append(f'{indent}- ')
        elif tag == 'table':
            self.add_newlines(2)
            self.flush_newlines()
        elif tag == 'tr':
            self.result.append('|')
        elif tag in {'th', 'td'}:
            self.result.append(' ')

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()

        if tag in self.ignore_tags:
            if self.skip_depth > 0:
                self.skip_depth -= 1
            return
        if self.skip_depth > 0:
            return

        if self.tag_stack and self.tag_stack[-1] == tag:
            self.tag_stack.pop()

        if tag in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'p', 'blockquote'}:
            self.add_newlines(2)
        elif tag in {'strong', 'b'}:
            self.result.append('**')
        elif tag in {'em', 'i'}:
            self.result.append('*')
        elif tag == 'code' and not self.in_pre:
            self.result.append('`')
        elif tag == 'pre':
            self.result.append('\n```')
            self.add_newlines(2)
            self.in_pre = False
        elif tag == 'a':
            href = (self.current_href or '').strip()
            if href:
                self.result.append(f']({href})')
            else:
                self.result.append(']')
            self.current_href = None
        elif tag == 'ul':
            if self.list_stack:
                self.list_stack.pop()
            self.add_newlines(2)
        elif tag == 'ol':
            if self.list_stack:
                self.list_stack.pop()
            if self.list_counters:
                self.list_counters.pop()
            self.add_newlines(2)
        elif tag == 'li':
            self.add_newlines(1)
        elif tag in {'th', 'td'}:
            self.result.append(' |')
        elif tag == 'tr':
            self.result.append('\n')

    def handle_data(self, data: str) -> None:
        if self.skip_depth > 0:
            return
        self.flush_newlines()
        if self.in_pre:
            self.result.append(data)
            return
        cleaned = re.sub(r'[ \t]+', ' ', data)
        cleaned = re.sub(r'\n\s*\n', '\n\n', cleaned)
        if cleaned.strip():
            self.result.append(cleaned)

    def get_markdown(self) -> str:
        content = ''.join(self.result)
        content = re.sub(r'\n{3,}', '\n\n', content)
        return content.strip() + '\n'


def format_markdown(markdown: str, markdown_dir: Path) -> tuple[str, Dict[str, object]]:
    summary: Dict[str, object] = {
        'removed_duplicate_headings': 0,
        'normalized_heading_levels': 0,
        'fixed_invalid_links': 0,
        'removed_missing_images': [],
        'removed_noise_lines': 0,
        'trimmed_blank_lines': 0,
    }

    text = markdown.replace('\r\n', '\n').replace('\r', '\n')
    text = text.replace('\xa0', ' ')
    text = re.sub(r'[ \t]+\n', '\n', text)
    text = re.sub(r'\*{4,}', '', text)
    text = re.sub(r'([^\n])(!\[[^\]]*\]\([^)]+\))', r'\1\n\n\2', text)
    text = re.sub(r'(!\[[^\]]*\]\([^)]+\))([^\n])', r'\1\n\n\2', text)

    def replace_invalid_link(match: re.Match[str]) -> str:
        label = normalize_inline_text(match.group(1))
        target = match.group(2).strip()
        lowered = target.lower()
        if lowered.startswith(INVALID_LINK_PATTERNS):
            summary['fixed_invalid_links'] = int(summary['fixed_invalid_links']) + 1
            return label
        return match.group(0)

    text = re.sub(r'\[([^\]]+?)\]\(([^)]+)\)', replace_invalid_link, text, flags=re.DOTALL)

    lines = text.split('\n')
    result_lines: List[str] = []
    previous_heading_text: Optional[str] = None
    previous_heading_level = 0
    in_code_block = False
    pending_heading_level: Optional[int] = None

    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped.startswith('```'):
            if stripped == '```':
                line = '```text'
            in_code_block = not in_code_block
            result_lines.append(line)
            continue

        if in_code_block:
            result_lines.append(line)
            continue

        if pending_heading_level is not None:
            if stripped == '':
                continue
            line = '#' * pending_heading_level + ' ' + normalize_inline_text(stripped)
            stripped = line
            pending_heading_level = None

        if any(pattern.match(stripped) for pattern in WECHAT_NOISE_PATTERNS):
            summary['removed_noise_lines'] = int(summary['removed_noise_lines']) + 1
            continue

        stripped = normalize_inline_text(stripped)
        line = normalize_inline_text(line)

        if not stripped:
            result_lines.append('')
            continue

        if _is_wechat_metadata_noise(stripped):
            summary['removed_noise_lines'] = int(summary['removed_noise_lines']) + 1
            continue

        heading_match = re.match(r'^(#{1,6})(?:\s+(.*))?$', stripped)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = normalize_inline_text(heading_match.group(2) or '')
            if not heading_text:
                pending_heading_level = level
                continue
            if heading_text and previous_heading_text == heading_text:
                summary['removed_duplicate_headings'] = int(summary['removed_duplicate_headings']) + 1
                continue
            if previous_heading_level and level > previous_heading_level + 1:
                level = previous_heading_level + 1
                summary['normalized_heading_levels'] = int(summary['normalized_heading_levels']) + 1
            previous_heading_level = level
            previous_heading_text = heading_text
            result_lines.append('#' * level + ' ' + heading_text)
            continue

        image_match = re.match(r'^!\[([^\]]*)\]\(([^)]+)\)$', stripped)
        if image_match:
            image_path = image_match.group(2).strip()
            if not image_path.startswith(('http://', 'https://')):
                candidate = (markdown_dir / image_path).resolve()
                if not candidate.exists():
                    cast_list = summary['removed_missing_images']
                    assert isinstance(cast_list, list)
                    cast_list.append(image_path)
                    continue
            alt = normalize_inline_text(image_match.group(1).strip())
            line = f'![{alt}]({image_path})'

        if re.match(r'^\s*[-*+]\s+', line):
            line = re.sub(r'^\s*[-*+]\s+', '- ', line)

        if stripped.startswith('>'):
            line = re.sub(r'^>\s*', '> ', stripped)

        if stripped == '***' or stripped == '___':
            line = '---'

        if '<' in line and '>' in line and not re.search(r'<https?://[^>]+>', line):
            line = re.sub(r'</?span[^>]*>', '', line)
            line = re.sub(r'</?font[^>]*>', '', line)
            line = re.sub(r'<br\s*/?>', '  ', line, flags=re.IGNORECASE)
            line = re.sub(r'<[^>]+>', '', line)

        line = normalize_inline_text(line)
        if not line:
            result_lines.append('')
            continue

        result_lines.append(line)

    text = '\n'.join(result_lines)
    text = _normalize_blank_lines(text)
    summary['trimmed_blank_lines'] = max(0, markdown.count('\n\n\n') - text.count('\n\n\n'))
    return text.strip() + '\n', summary


def _normalize_blank_lines(markdown: str) -> str:
    lines = markdown.split('\n')
    normalized: List[str] = []
    blank_count = 0
    in_code_block = False

    for raw_line in lines:
        stripped = raw_line.strip()
        if stripped.startswith('```'):
            in_code_block = not in_code_block
            blank_count = 0
            if normalized and normalized[-1] != '':
                normalized.append('')
            normalized.append(raw_line.rstrip())
            continue

        if in_code_block:
            normalized.append(raw_line.rstrip())
            continue

        if stripped == '':
            blank_count += 1
            if blank_count <= 1:
                normalized.append('')
            continue

        blank_count = 0
        previous = normalized[-1] if normalized else None
        if stripped.startswith('#') or stripped.startswith('![') or stripped == '---':
            if previous not in (None, ''):
                normalized.append('')
        normalized.append(raw_line.rstrip())

    while normalized and normalized[-1] == '':
        normalized.pop()
    return '\n'.join(normalized)


def _is_wechat_metadata_noise(line: str) -> bool:
    if not line:
        return False
    if line == '原创':
        return True
    if line.startswith('原创') and '在小说阅读器中沉浸阅读' in line:
        return True
    if '在小说阅读器中沉浸阅读' in line:
        return True
    if line.startswith('原创') and len(line) < 40:
        return True
    if line.startswith('微信扫一扫'):
        return True
    if line.startswith('喜欢此内容的人还喜欢'):
        return True
    if line.startswith('继续滑动看下一个'):
        return True
    if line.startswith('作者：') and len(line) < 40:
        return True
    if line.startswith('公众号：') and len(line) < 40:
        return True
    return False


def convert_article_to_markdown(article: ArticleData, output_dir: Path, timeout: int) -> tuple[str, int, str]:
    downloader = MarkdownImageDownloader(
        output_dir=output_dir,
        base_url=article.original_url,
        timeout=timeout,
    )
    parser = HTMLToMarkdownParser(downloader)

    article_html = f'''
    <article>
        <h1>{html.escape(article.title)}</h1>
        <p>作者: {html.escape(article.author or '未知')}</p>
        <p>公众号: {html.escape(article.account_name or '未知')}</p>
        <div>{article.content_html}</div>
        <p>原文链接: <a href="{html.escape(article.original_url)}">{html.escape(article.original_url)}</a></p>
    </article>
    '''

    parser.feed(article_html)
    return parser.get_markdown(), downloader.image_index, article_html


def build_output_paths(title: str, output_base_dir: Path) -> tuple[Path, Path, str]:
    safe_title = sanitize_filename(title)
    folder_number = get_next_folder_number(output_base_dir)
    folder_name = f'{folder_number:02d}_{safe_title}'
    output_dir = output_base_dir / folder_name
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / f'{safe_title}.md'
    return output_dir, markdown_path, folder_name


def run_pipeline(url: str, output_base_dir: Path, save_html: bool, timeout: int) -> Dict[str, object]:
    pipeline = WeChatArticlePipeline(timeout=timeout)
    if not pipeline.validate_url(url):
        raise ValueError('无效的微信文章链接，仅支持 mp.weixin.qq.com 或 weixin.qq.com')

    source_html = pipeline.fetch_html(url)
    article = pipeline.extract_article(source_html, url)
    output_dir, markdown_path, folder_name = build_output_paths(article.title, output_base_dir)

    raw_markdown, image_count, clean_article_html = convert_article_to_markdown(article, output_dir, timeout)
    formatted_markdown, format_summary = format_markdown(raw_markdown, output_dir)
    markdown_path.write_text(formatted_markdown, encoding='utf-8')

    html_path = None
    if save_html:
        html_path = output_dir / 'source.html'
        html_path.write_text(pipeline.build_clean_html(article), encoding='utf-8')

    return {
        'title': article.title,
        'author': article.author,
        'account_name': article.account_name,
        'output_dir': str(output_dir),
        'folder_name': folder_name,
        'markdown_file': str(markdown_path),
        'html_file': str(html_path) if html_path else None,
        'image_count': image_count,
        'format_summary': format_summary,
        'clean_html_preview_length': len(clean_article_html),
    }


def print_summary(result: Dict[str, object]) -> None:
    print('✅ WeChat 文章处理完成\n')
    print(f"标题: {result['title']}")
    if result['author']:
        print(f"作者: {result['author']}")
    if result['account_name']:
        print(f"公众号: {result['account_name']}")
    print(f"输出目录: {result['output_dir']}")
    print(f"Markdown: {result['markdown_file']}")
    if result['html_file']:
        print(f"HTML: {result['html_file']}")
    print(f"图片数量: {result['image_count']}")

    summary = result['format_summary']
    assert isinstance(summary, dict)
    missing_images = summary.get('removed_missing_images', [])
    print('\n格式化摘要:')
    print(f"- 移除重复标题: {summary.get('removed_duplicate_headings', 0)} 处")
    print(f"- 规范标题层级: {summary.get('normalized_heading_levels', 0)} 处")
    print(f"- 清理无效链接: {summary.get('fixed_invalid_links', 0)} 处")
    print(f"- 移除公众号噪音行: {summary.get('removed_noise_lines', 0)} 处")
    print(f"- 调整空行: {summary.get('trimmed_blank_lines', 0)} 处")
    print(f"- 删除缺失图片引用: {len(missing_images)} 处")
    if missing_images:
        print('  ' + ', '.join(str(item) for item in missing_images))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Fetch WeChat public articles and convert them to formatted Markdown.'
    )
    parser.add_argument('url', help='微信文章链接')
    parser.add_argument(
        '--output-dir',
        default='articles',
        help='输出根目录，默认: ./articles',
    )
    parser.add_argument(
        '--save-html',
        action='store_true',
        help='额外保存清洗后的 HTML 文件',
    )
    parser.add_argument(
        '--timeout',
        type=int,
        default=30,
        help='网络请求超时秒数，默认 30',
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        result = run_pipeline(
            url=args.url,
            output_base_dir=Path(args.output_dir).resolve(),
            save_html=args.save_html,
            timeout=args.timeout,
        )
    except requests.RequestException as error:
        print(f'抓取失败: {error}', file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        print(f'处理失败: {error}', file=sys.stderr)
        sys.exit(1)

    print_summary(result)


if __name__ == '__main__':
    main()