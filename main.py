import json
import logging
import os
import re
import sys
import time
from calendar import timegm
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import feedparser
import pytz
import requests
import yaml
from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from openai import OpenAI


BASE_DIR = Path(__file__).resolve().parent
TIMEZONE = pytz.timezone("Asia/Shanghai")
REQUEST_TIMEOUT = 15
MAX_CANDIDATES_FOR_LLM = 20
MIN_SCORE = 60
WECOM_MARKDOWN_LIMIT = 3800

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


MEDICAL_DEVICE_KEYWORDS = [
    "医疗器械", "医疗设备", "医用设备", "器械", "设备更新", "注册证", "创新医疗器械",
    "体外诊断", "IVD", "检验设备", "AED", "自动体外除颤", "生命支持", "呼吸机",
    "监护仪", "除颤仪", "急救设备", "体检设备", "康复设备", "中医康复",
    "五官科", "眼科设备", "耳鼻喉", "AI医疗", "人工智能医疗器械", "辅助诊断",
]

BUSINESS_VALUE_KEYWORDS = [
    "集采", "集中采购", "带量采购", "采购", "招标", "挂网", "医保支付", "医保",
    "价格治理", "补贴", "设备配置", "设备更新", "县域", "基层", "乡镇卫生院",
    "社区卫生服务中心", "县级医院", "民营医院", "诊所", "体检中心", "招商",
    "渠道", "经销商", "合作", "注册审批", "注册证", "质量抽检", "监管", "合规",
    "反腐", "飞行检查", "公立医院", "市场准入",
]

CATEGORY_KEYWORDS = {
    "政策监管": ["监管", "政策", "注册证", "审批", "质量抽检", "飞行检查", "合规", "反腐", "药监"],
    "集采与医保": ["集采", "集中采购", "带量采购", "医保", "挂网", "价格治理", "招采"],
    "基层 / 县域市场机会": ["基层", "县域", "乡镇卫生院", "社区卫生服务中心", "县级医院", "补贴", "设备配置", "设备更新"],
    "企业新品与技术创新": ["新品", "研发", "创新医疗器械", "注册审批", "注册证", "高端医疗装备"],
    "渠道招商与商业合作": ["招商", "渠道", "经销商", "合作", "采购机会", "供应商"],
    "AI 医疗器械动态": ["AI", "人工智能", "智能诊断", "辅助诊断", "数字化"],
}

EXCLUDE_KEYWORDS = [
    "保健品", "医美", "美容", "养生", "单抗", "中成药", "药品说明书", "临床论文",
    "论文", "SCI", "义诊", "健康科普", "医院文化", "护士节", "党建活动",
]

SOURCE_PRIORITY_SCORE = {"high": 25, "medium": 15, "low": 8}
SOURCE_CATEGORY_SCORE = {
    "regulator": 25,
    "procurement": 25,
    "government": 22,
    "association": 16,
    "media": 12,
    "industry": 10,
}


def load_sources() -> list[dict[str, Any]]:
    """Read source definitions from sources.yml."""
    path = BASE_DIR / "sources.yml"
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    sources = data.get("sources", [])
    logger.info("Loaded %s news sources.", len(sources))
    return sources


def get_time_window() -> tuple[datetime, datetime]:
    """Return Beijing time window: yesterday 17:00 to today 17:00."""
    now = datetime.now(TIMEZONE)
    end_time = now.replace(hour=17, minute=0, second=0, microsecond=0)
    if now < end_time:
        end_time -= timedelta(days=1)
    start_time = end_time - timedelta(days=1)
    return start_time, end_time


def fetch_rss_source(source: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch one RSS source. One failing source will not stop the whole job."""
    logger.info("Fetching RSS source: %s", source.get("name"))
    feed = feedparser.parse(source["url"])
    items = []
    for entry in feed.entries:
        published_at = None
        if getattr(entry, "published_parsed", None):
            published_at = datetime.fromtimestamp(timegm(entry.published_parsed), pytz.utc).astimezone(TIMEZONE)
        elif getattr(entry, "updated_parsed", None):
            published_at = datetime.fromtimestamp(timegm(entry.updated_parsed), pytz.utc).astimezone(TIMEZONE)

        items.append(
            {
                "title": getattr(entry, "title", "").strip(),
                "url": getattr(entry, "link", "").strip(),
                "source": source.get("name", ""),
                "published_at": published_at,
                "summary": BeautifulSoup(getattr(entry, "summary", ""), "html.parser").get_text(" ", strip=True),
                "category": source.get("category", ""),
                "priority": source.get("priority", "low"),
                "source_type": source.get("type", "rss"),
            }
        )
    return items


def fetch_webpage_source(source: dict[str, Any]) -> list[dict[str, Any]]:
    """Fetch titles and links from a normal webpage using a conservative generic parser."""
    logger.info("Fetching webpage source: %s", source.get("name"))
    headers = {
        "User-Agent": "Mozilla/5.0 medical-news-agent/1.0 (+https://github.com/)",
    }
    response = requests.get(source["url"], headers=headers, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding

    soup = BeautifulSoup(response.text, "html.parser")
    items = []
    seen_urls = set()
    for tag in soup.find_all("a", href=True):
        title = tag.get_text(" ", strip=True)
        if len(title) < 6 or len(title) > 120:
            continue
        href = tag["href"].strip()
        if href.startswith(("javascript:", "#", "mailto:")):
            continue
        url = urljoin(source["url"], href)
        if url in seen_urls:
            continue
        seen_urls.add(url)

        context_text = tag.parent.get_text(" ", strip=True) if tag.parent else title
        published_at = extract_datetime_from_text(context_text) or extract_datetime_from_text(url)
        items.append(
            {
                "title": title,
                "url": url,
                "source": source.get("name", ""),
                "published_at": published_at,
                "summary": context_text[:240],
                "category": source.get("category", ""),
                "priority": source.get("priority", "low"),
                "source_type": source.get("type", "webpage"),
            }
        )
    return items


def extract_datetime_from_text(text: str) -> datetime | None:
    """Extract common Chinese date formats from a title, list row, or URL."""
    patterns = [
        r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?\s*(\d{1,2}:\d{1,2})?",
        r"(20\d{2})(\d{2})(\d{2})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        try:
            if len(match.groups()) >= 4 and match.group(4):
                raw = f"{match.group(1)}-{match.group(2)}-{match.group(3)} {match.group(4)}"
            else:
                raw = f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
            parsed = date_parser.parse(raw)
            return TIMEZONE.localize(parsed) if parsed.tzinfo is None else parsed.astimezone(TIMEZONE)
        except Exception:
            continue
    return None


def normalize_news_item(item: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize one news item into the fields used by the pipeline."""
    title = clean_text(item.get("title", ""))
    url = item.get("url", "").strip()
    if not title or not url:
        return None

    published_at = item.get("published_at")
    if isinstance(published_at, str):
        try:
            parsed = date_parser.parse(published_at)
            published_at = TIMEZONE.localize(parsed) if parsed.tzinfo is None else parsed.astimezone(TIMEZONE)
        except Exception:
            published_at = None

    return {
        "title": title,
        "url": url,
        "source": clean_text(item.get("source", "")),
        "published_at": published_at,
        "summary": clean_text(item.get("summary", "")),
        "category": item.get("category", ""),
        "priority": item.get("priority", "low"),
        "source_type": item.get("source_type", ""),
        "score": 0,
    }


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def filter_by_time(
    news_items: list[dict[str, Any]],
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    """Keep items inside the Beijing-time window. Unknown dates are dropped."""
    filtered = []
    for item in news_items:
        published_at = item.get("published_at")
        if not published_at:
            continue
        if published_at.tzinfo is None:
            published_at = TIMEZONE.localize(published_at)
        published_at = published_at.astimezone(TIMEZONE)
        if start_time <= published_at <= end_time:
            item["published_at"] = published_at
            filtered.append(item)
    logger.info("Kept %s items inside time window.", len(filtered))
    return filtered


def rule_score_news(item: dict[str, Any]) -> int:
    """Score one news item from 0 to 100 before sending candidates to MiniMax."""
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    if any(keyword in text for keyword in EXCLUDE_KEYWORDS):
        return 0

    score = 0
    score += SOURCE_PRIORITY_SCORE.get(item.get("priority", "low"), 8)
    score += SOURCE_CATEGORY_SCORE.get(item.get("category", ""), 8)

    device_hits = count_keyword_hits(text, MEDICAL_DEVICE_KEYWORDS)
    business_hits = count_keyword_hits(text, BUSINESS_VALUE_KEYWORDS)
    score += min(device_hits * 6, 24)
    score += min(business_hits * 5, 24)

    published_at = item.get("published_at")
    if published_at:
        hours_old = max((datetime.now(TIMEZONE) - published_at).total_seconds() / 3600, 0)
        score += max(0, int(12 - hours_old / 2))

    if "医疗器械" not in text and device_hits == 0:
        score -= 25
    if business_hits == 0:
        score -= 15

    return max(0, min(score, 100))


def count_keyword_hits(text: str, keywords: list[str]) -> int:
    return sum(1 for keyword in keywords if keyword.lower() in text.lower())


def deduplicate_news(news_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by title similarity and keep the more authoritative item."""
    sorted_items = sorted(
        news_items,
        key=lambda x: (
            x.get("score", 0),
            SOURCE_CATEGORY_SCORE.get(x.get("category", ""), 0),
            SOURCE_PRIORITY_SCORE.get(x.get("priority", "low"), 0),
        ),
        reverse=True,
    )
    kept = []
    for item in sorted_items:
        duplicate_index = None
        for index, existing in enumerate(kept):
            if title_similarity(item["title"], existing["title"]) >= 0.82:
                duplicate_index = index
                break
        if duplicate_index is None:
            kept.append(item)
            continue
        if is_better_source(item, kept[duplicate_index]):
            kept[duplicate_index] = item
    logger.info("Kept %s items after deduplication.", len(kept))
    return kept


def title_similarity(left: str, right: str) -> float:
    left = re.sub(r"[^\w\u4e00-\u9fff]", "", left)
    right = re.sub(r"[^\w\u4e00-\u9fff]", "", right)
    return SequenceMatcher(None, left, right).ratio()


def is_better_source(candidate: dict[str, Any], current: dict[str, Any]) -> bool:
    candidate_rank = SOURCE_CATEGORY_SCORE.get(candidate.get("category", ""), 0) + SOURCE_PRIORITY_SCORE.get(candidate.get("priority", ""), 0)
    current_rank = SOURCE_CATEGORY_SCORE.get(current.get("category", ""), 0) + SOURCE_PRIORITY_SCORE.get(current.get("priority", ""), 0)
    return candidate_rank > current_rank or candidate.get("score", 0) > current.get("score", 0)


def build_candidate_payload(news_items: list[dict[str, Any]]) -> str:
    """Build compact JSON input for MiniMax."""
    payload = []
    for index, item in enumerate(news_items[:MAX_CANDIDATES_FOR_LLM], start=1):
        published_at = item["published_at"].strftime("%Y-%m-%d %H:%M")
        payload.append(
            {
                "id": index,
                "title": item["title"],
                "source": item["source"],
                "published_at": published_at,
                "score": item.get("score", 0),
                "source_category": item.get("category", ""),
                "summary": item.get("summary", "")[:300],
                "url": item["url"],
            }
        )
    return json.dumps(payload, ensure_ascii=False, indent=2)


def generate_briefing_with_minimax(
    candidate_payload: str,
    start_time: datetime,
    end_time: datetime,
) -> str:
    """Call MiniMax through the OpenAI-compatible Chat Completions API."""
    api_key = os.getenv("MINIMAX_API_KEY")
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY is not configured.")

    system_prompt = (BASE_DIR / "prompt.md").read_text(encoding="utf-8")
    start_text = start_time.strftime("%Y-%m-%d %H:%M")
    end_text = end_time.strftime("%Y-%m-%d %H:%M")
    user_prompt = f"""
请根据下面的候选新闻生成企业微信群 Markdown 简报。

硬性要求：
1. 只保留真正有医疗器械 B 端业务价值的新闻。
2. 最终保留 3-8 条；如果没有符合要求的新闻，输出无新闻提示。
3. 不要编造候选新闻之外的事实、链接、标题。
4. 时间范围必须写成：{start_text} 至 {end_text}
5. 原文入口必须使用候选新闻中的 URL。
6. 每条新闻必须归入最合适的模块；没有内容的模块不要输出。

候选新闻 JSON：
{candidate_payload}
""".strip()

    client = OpenAI(
        api_key=api_key,
        base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.io/v1"),
    )
    try:
        response = client.chat.completions.create(
            model=os.getenv("MINIMAX_MODEL", "MiniMax-M2"),
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        content = response.choices[0].message.content
        if not content:
            raise RuntimeError("MiniMax returned an empty response.")
        return content.strip()
    except Exception as exc:
        logger.exception("MiniMax briefing generation failed: %s", exc)
        raise


def send_to_wecom(markdown_text: str) -> bool:
    """Send Markdown message to WeCom group bot with retry and safe logs."""
    webhook = os.getenv("WECOM_WEBHOOK")
    if not webhook:
        logger.warning("WECOM_WEBHOOK is not configured. Printing briefing instead of sending.")
        print(markdown_text)
        return False

    chunks = split_markdown(markdown_text, WECOM_MARKDOWN_LIMIT)
    all_success = True
    for index, chunk in enumerate(chunks, start=1):
        content = chunk if len(chunks) == 1 else f"{chunk}\n\n> 第 {index}/{len(chunks)} 段"
        payload = {"msgtype": "markdown", "markdown": {"content": content}}
        success = False
        for attempt in range(1, 4):
            try:
                response = requests.post(webhook, json=payload, timeout=REQUEST_TIMEOUT)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("errcode") == 0:
                        success = True
                        break
                    logger.warning("WeCom push failed, attempt %s, response: %s", attempt, data)
                else:
                    logger.warning(
                        "WeCom push HTTP failed, attempt %s, status=%s, body=%s",
                        attempt,
                        response.status_code,
                        response.text[:500],
                    )
            except Exception as exc:
                logger.warning("WeCom push exception, attempt %s: %s", attempt, exc)
            time.sleep(attempt * 2)
        all_success = all_success and success
    return all_success


def split_markdown(text: str, limit: int) -> list[str]:
    """Split long Markdown by lines to reduce WeCom rejection risk."""
    if len(text) <= limit:
        return [text]
    chunks = []
    current = ""
    for line in text.splitlines():
        if len(current) + len(line) + 1 > limit:
            if current:
                chunks.append(current.rstrip())
            current = line + "\n"
        else:
            current += line + "\n"
    if current.strip():
        chunks.append(current.rstrip())
    return chunks


def build_no_news_message(start_time: datetime, end_time: datetime) -> str:
    return (
        "# 医疗器械行业每日情报简报\n"
        f"时间范围：{start_time.strftime('%Y-%m-%d %H:%M')} 至 {end_time.strftime('%Y-%m-%d %H:%M')}\n\n"
        "今日无符合条件的高价值医疗器械行业新闻。"
    )


def build_error_message(start_time: datetime, end_time: datetime, reason: str) -> str:
    return (
        "# 医疗器械行业每日情报简报\n"
        f"时间范围：{start_time.strftime('%Y-%m-%d %H:%M')} 至 {end_time.strftime('%Y-%m-%d %H:%M')}\n\n"
        f"今日新闻 Agent 运行异常：{reason}\n\n"
        "请查看 GitHub Actions 日志定位原因。"
    )


def deliver_or_exit(markdown_text: str) -> None:
    """Send message and fail the workflow when WeCom delivery does not succeed."""
    if not send_to_wecom(markdown_text):
        logger.error("WeCom message was not delivered. Please check WECOM_WEBHOOK in GitHub Secrets.")
        sys.exit(1)


def main() -> None:
    start_time, end_time = get_time_window()
    logger.info("News window: %s to %s", start_time, end_time)

    sources = load_sources()
    raw_items = []
    failed_sources = 0
    for source in sources:
        try:
            if source.get("type") == "rss":
                raw_items.extend(fetch_rss_source(source))
            else:
                raw_items.extend(fetch_webpage_source(source))
        except Exception as exc:
            failed_sources += 1
            logger.warning("Source failed: %s, error: %s", source.get("name"), exc)

    if failed_sources == len(sources) and sources:
        logger.error("All news sources failed.")
        deliver_or_exit(build_error_message(start_time, end_time, "全部新闻源抓取失败"))
        return

    normalized_items = []
    for item in raw_items:
        normalized = normalize_news_item(item)
        if normalized:
            normalized_items.append(normalized)
    logger.info("Normalized %s news items.", len(normalized_items))

    time_filtered = filter_by_time(normalized_items, start_time, end_time)
    scored_items = []
    for item in time_filtered:
        item["score"] = rule_score_news(item)
        if item["score"] >= MIN_SCORE:
            scored_items.append(item)
    logger.info("Kept %s items with score >= %s.", len(scored_items), MIN_SCORE)

    deduped_items = deduplicate_news(scored_items)
    candidates = sorted(deduped_items, key=lambda x: x.get("score", 0), reverse=True)[:MAX_CANDIDATES_FOR_LLM]

    if not candidates:
        deliver_or_exit(build_no_news_message(start_time, end_time))
        return

    candidate_payload = build_candidate_payload(candidates)
    try:
        briefing = generate_briefing_with_minimax(candidate_payload, start_time, end_time)
    except Exception:
        deliver_or_exit(build_error_message(start_time, end_time, "MiniMax 生成简报失败"))
        return

    deliver_or_exit(briefing)


if __name__ == "__main__":
    main()
