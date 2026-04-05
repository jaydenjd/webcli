"""
@Time ： 2026/4/5 18:45
@Auth ： 新南
"""
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from typing import List, Dict, Optional
import re


def fetch_ithome_daily_rank() -> Optional[List[Dict]]:
    """
    抓取 IT之家日榜数据
    返回格式: [
        {
            "rank": 1,
            "title": "标题",
            "url": "https://m.ithome.com/html/xxxxx.htm",
            "pc_url": "https://www.ithome.com/html/xxxxx.htm",
            "post_time": "昨日 19:47",
            "comment_count": 372,
            "thumbnail": "https://img.ithome.com/newsuploadfiles/thumbnail/2025/04/xxxxx_240.jpg"
        },
        ...
    ]
    """
    url = "https://m.ithome.com/rankm/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        response.encoding = 'utf-8'
    except requests.RequestException as e:
        print(f"请求失败: {e}")
        return None

    soup = BeautifulSoup(response.text, 'html.parser')

    # 定位到“日榜”区块
    # 根据页面结构，日榜是第一个 .rank-wrap 或 直接按顺序取前12个 .one-img-plc
    # 方法：找到所有条目后，日榜对应索引 0~11
    all_items = soup.select('div.one-img-plc')
    if not all_items:
        print("未找到榜单条目，页面结构可能已变化")
        return None

    # 日榜是前12条
    daily_items = all_items[:12]
    daily_data = []

    for item in daily_items:
        # 提取排名
        rank_elem = item.select_one('div.plc-image > span.rank-num')
        rank = int(rank_elem.text.strip()) if rank_elem and rank_elem.text.strip().isdigit() else None

        # 提取链接和ID
        link_elem = item.select_one('a[role="option"]')
        if not link_elem:
            continue
        href = link_elem.get('href', '')
        # 提取ID (例如 /html/123456.htm -> 123456)
        id_match = re.search(r'/html/(\d+)\.htm', href)
        article_id = id_match.group(1) if id_match else None

        # 标题
        title_elem = item.select_one('p.plc-title')
        title = title_elem.text.strip() if title_elem else ''

        # 发布时间
        time_elem = item.select_one('span.post-time')
        post_time = time_elem.text.strip() if time_elem else ''

        # 评论数
        comment_elem = item.select_one('span.review-num')
        comment_text = comment_elem.text.strip() if comment_elem else '0评'
        comment_count = int(re.search(r'(\d+)', comment_text).group(1)) if re.search(r'(\d+)', comment_text) else 0

        # 缩略图
        img_elem = item.select_one('img[data-original]')
        thumbnail = img_elem.get('data-original', '') if img_elem else ''

        # 构建URL
        mobile_url = f"https://m.ithome.com/html/{article_id}.htm" if article_id else href
        pc_url = f"https://www.ithome.com/html/{article_id}.htm" if article_id else ''

        daily_data.append({
            "rank": rank,
            "title": title,
            "url": mobile_url,
            "pc_url": pc_url,
            "post_time": post_time,
            "comment_count": comment_count,
            "thumbnail": thumbnail
        })

    return daily_data


def print_daily_rank(data: List[Dict]):
    """打印日榜数据，便于查看"""
    if not data:
        print("无数据")
        return

    print(f"IT之家日榜 - 抓取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 80)
    for item in data:
        print(f"排名: {item['rank']}")
        print(f"标题: {item['title']}")
        print(f"链接: {item['url']}")
        print(f"时间: {item['post_time']}")
        print(f"评论: {item['comment_count']}条")
        print(f"缩略图: {item['thumbnail']}")
        print("-" * 80)


if __name__ == "__main__":
    daily_rank = fetch_ithome_daily_rank()
    if daily_rank:
        print_daily_rank(daily_rank)
        # 可以进一步处理数据，例如保存为JSON
        # import json
        # with open('ithome_daily.json', 'w', encoding='utf-8') as f:
        #     json.dump(daily_rank, f, ensure_ascii=False, indent=2)
    else:
        print("抓取失败")