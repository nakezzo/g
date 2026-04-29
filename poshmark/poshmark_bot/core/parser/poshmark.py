import asyncio
import json
import random
import re
from typing import Dict, List, Optional, Tuple
import aiohttp
from bs4 import BeautifulSoup
from ...models import PoshmarkItem
from ...config import POSHMARK_CATEGORIES

class PoshmarkParser:
    BASE_URL = "https://poshmark.com"

    def __init__(self, config: dict, log_cb=None):
        self.config      = config
        self.log_cb      = log_cb
        self.is_running  = False
        self.seen_items  = set()
        self.seen_users  = set()
        self.semaphore   = asyncio.Semaphore(config.get("max_concurrent", 10))
        self.stats       = {"found": 0, "valid": 0, "errors": 0}
        self._proxy_idx  = config.get("proxy_idx", 0)

    def log(self, msg: str):
        if self.log_cb:
            self.log_cb(msg)

    def _next_proxy(self) -> Optional[str]:
        proxies = self.config.get("proxies", [])
        if not proxies:
            return None
        proxy = proxies[self._proxy_idx % len(proxies)]
        self._proxy_idx = (self._proxy_idx + 1) % len(proxies)
        return proxy

    def _headers(self) -> dict:
        return {
            "User-Agent": random.choice([
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
            ]),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

    def _clean_username(self, username: str) -> Optional[str]:
        if not username:
            return None
        cleaned = re.sub(r"[^a-z0-9._]", "", username.lower().strip())
        cleaned = re.sub(r"\.{2,}", ".", cleaned).strip(".")
        return cleaned if len(cleaned) >= 2 else None

    def _passes_filters(self, item: PoshmarkItem) -> Tuple[bool, str]:
        def num(s):
            digits = re.findall(r"\d+", s or "")
            return int(digits[0]) if digits else 0

        max_sales   = self.config.get("max_sales", 0)
        max_reviews = self.config.get("max_reviews", 0)

        if max_sales > 0 and num(item.sold_count) > max_sales:
            return False, f"продажи {num(item.sold_count)} > {max_sales}"
        if max_reviews > 0 and num(item.reviews_count) > max_reviews:
            return False, f"отзывов {num(item.reviews_count)} > {max_reviews}"
        return True, ""

    async def _fetch(self, session: aiohttp.ClientSession, url: str,
                     proxy: str = None, retry: int = 0) -> Optional[str]:
        kwargs = {"headers": self._headers(), "timeout": aiohttp.ClientTimeout(total=15)}
        if proxy and proxy.startswith("http"):
            kwargs["proxy"] = proxy
        try:
            async with self.semaphore:
                async with session.get(url, **kwargs) as r:
                    if r.status == 200:
                        return await r.text()
                    if r.status == 403:
                        self.log(f"⚠️ 403 Forbidden: {url[:60]}")
                        await asyncio.sleep(5)
                        return None
                    if r.status in (429, 503) and retry < 3:
                        await asyncio.sleep(4 * (retry + 1))
                        return await self._fetch(session, url, proxy, retry + 1)
                    self.log(f"⚠️ HTTP {r.status}: {url[:60]}")
        except asyncio.TimeoutError:
            if retry < 2:
                await asyncio.sleep(2)
                return await self._fetch(session, url, proxy, retry + 1)
        except Exception:
            if retry < 1:
                await asyncio.sleep(1)
                return await self._fetch(session, url, proxy, retry + 1)
            self.stats["errors"] += 1
        return None

    def _parse_feed_page(self, html: str) -> List[dict]:
        results = []
        if not html:
            return results
        try:
            soup = BeautifulSoup(html, "html.parser")
            for script in soup.find_all("script", type="application/json"):
                try:
                    data = json.loads(script.string or "")
                    items = []
                    if isinstance(data, dict):
                        def find_listings(obj, depth=0):
                            if depth > 8: return
                            if isinstance(obj, list):
                                for item in obj:
                                    if isinstance(item, dict) and "creator" in item and "id" in item:
                                        items.append(item)
                                    else:
                                        find_listings(item, depth+1)
                            elif isinstance(obj, dict):
                                for v in obj.values():
                                    find_listings(v, depth+1)
                        find_listings(data)

                    for item in items[:50]:
                        creator = item.get("creator", {})
                        username = creator.get("login", "") or creator.get("username", "")
                        title    = item.get("title", "")
                        item_id  = item.get("id", "")
                        if username and item_id:
                            results.append({
                                "url":      f"{self.BASE_URL}/listing/{item_id}",
                                "title":    title,
                                "username": username,
                            })
                except Exception:
                    pass

            if not results:
                next_data = soup.find("script", id="__NEXT_DATA__")
                if next_data and next_data.string:
                    try:
                        data = json.loads(next_data.string)
                        props = data.get("props", {}).get("pageProps", {})
                        for key in ["listings", "posts", "data", "items", "feed"]:
                            lst = props.get(key, [])
                            if isinstance(lst, list):
                                for item in lst:
                                    if not isinstance(item, dict): continue
                                    creator  = item.get("creator", {}) or {}
                                    username = creator.get("login", "") or item.get("seller_handle", "")
                                    title    = item.get("title", "")
                                    iid      = item.get("id", "")
                                    if username:
                                        results.append({
                                            "url":      f"{self.BASE_URL}/listing/{iid}" if iid else "",
                                            "title":    title,
                                            "username": username,
                                        })
                    except Exception:
                        pass

            if not results:
                cards = (
                    soup.find_all("div", attrs={"data-et-prop-location": "listing_tile"}) or
                    soup.find_all("div", class_=re.compile(r"card--listing|listing-card|item-box")) or
                    soup.find_all("li", class_=re.compile(r"card|listing|tile"))
                )
                for card in cards:
                    u_tag = (
                        card.find("a", href=re.compile(r"/closet/")) or
                        card.find("span", class_=re.compile(r"username|seller")) or
                        card.find("a", class_=re.compile(r"seller|user"))
                    )
                    username = ""
                    if u_tag:
                        href = u_tag.get("href", "")
                        m = re.search(r"/closet/([^/?#]+)", href)
                        if m:
                            username = m.group(1)
                        else:
                            username = u_tag.get_text(strip=True).replace("@", "")

                    a_tag = card.find("a", href=re.compile(r"/listing/"))
                    url   = ""
                    if a_tag:
                        href = a_tag.get("href", "")
                        url  = f"{self.BASE_URL}{href}" if href.startswith("/") else href

                    title = ""
                    t_tag = card.find("a", class_=re.compile(r"title"))
                    if t_tag:
                        title = t_tag.get_text(strip=True)

                    if username or url:
                        results.append({"url": url, "title": title, "username": username})

            if not results:
                for a in soup.find_all("a", href=re.compile(r"poshmark\.com/closet/|/closet/")):
                    href = a.get("href", "")
                    m    = re.search(r"/closet/([^/?#\"]+)", href)
                    if m:
                        username = m.group(1)
                        if len(username) >= 2:
                            results.append({"url": "", "title": "", "username": username})

        except Exception:
            self.stats["errors"] += 1
        return results

    async def _get_user_details(self, username: str,
                                session: aiohttp.ClientSession,
                                proxy: str = None) -> dict:
        url  = f"{self.BASE_URL}/closet/{username}"
        html = await self._fetch(session, url, proxy)
        result = {"sold": "", "listings": "", "reviews": ""}
        if not html:
            return result
        try:
            soup = BeautifulSoup(html, "html.parser")
            next_data = soup.find("script", id="__NEXT_DATA__")
            if next_data and next_data.string:
                data  = json.loads(next_data.string)
                props = data.get("props", {}).get("pageProps", {})
                user  = props.get("user", {}) or props.get("seller", {}) or {}
                result["sold"]     = str(user.get("sold_count", "") or user.get("salesCount", ""))
                result["listings"] = str(user.get("listing_count", "") or user.get("listingsCount", ""))
                result["reviews"]  = str(user.get("love_count", "") or user.get("followersCount", ""))
                if result["sold"] or result["listings"]:
                    return result

            stats = soup.find("div", class_=re.compile(r"user-statistics|seller-details|closet-info"))
            if stats:
                text = stats.get_text()
                for m in re.finditer(r"(\d[\d,]*)\s*(Sold|Listings|Followers|Love|Items)", text, re.I):
                    n, label = m.group(1), m.group(2).lower()
                    if "sold" in label:   result["sold"]     = n
                    if "listing" in label: result["listings"] = n
                    if "follow" in label or "love" in label: result["reviews"] = n
        except Exception:
            pass
        return result

    async def start(self, item_queue: asyncio.Queue):
        self.is_running = True
        self.seen_items.clear()
        self.seen_users.clear()
        categories = self.config.get("selected_categories",
                                     list(POSHMARK_CATEGORIES.values()))
        proxies = self.config.get("proxies", [])

        connector = aiohttp.TCPConnector(limit=50, ssl=False)
        timeout   = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            self.log(f"🚀 Парсер запущен | категорий: {len(categories)} | прокси: {len(proxies)}")
            tasks = [
                asyncio.create_task(self._watch(cat, session, item_queue))
                for cat in categories
            ]
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _watch(self, category: str, session: aiohttp.ClientSession,
                     item_queue: asyncio.Queue):
        url      = f"{self.BASE_URL}{category}?sort_by=added_desc"
        delay    = self.config.get("cycle_delay", 2.0)
        req_d    = self.config.get("request_delay", 0.5)
        per_page = self.config.get("items_per_page", 30)

        while self.is_running:
            proxy = self._next_proxy()
            html  = await self._fetch(session, url, proxy)
            if html:
                raw_items = self._parse_feed_page(html)
                processed = 0
                for raw in raw_items[:per_page]:
                    if not self.is_running:
                        return
                    item = await self._process_raw(raw, session, proxy)
                    if item:
                        await item_queue.put(item)
                        processed += 1
                    await asyncio.sleep(req_d)
                if processed:
                    self.log(f"📦 {category.split('/')[-1]}: +{processed} новых")
            else:
                self.log(f"⚠️ Нет ответа от {category.split('/')[-1]}")
                await asyncio.sleep(10)
            await asyncio.sleep(delay)

    async def _process_raw(self, raw: dict,
                            session: aiohttp.ClientSession,
                            proxy: str = None) -> Optional[PoshmarkItem]:
        try:
            username = self._clean_username(raw.get("username", ""))
            if not username or username in self.seen_users:
                return None

            url   = raw.get("url", "")
            title = raw.get("title", "")

            if url and url in self.seen_items:
                return None

            self.stats["found"] += 1
            details = await self._get_user_details(username, session, proxy)

            item = PoshmarkItem(
                username      = username,
                email         = f"{username}@gmail.com",
                item_title    = title,
                item_url      = url,
                sold_count    = details["sold"],
                listings_count= details["listings"],
                reviews_count = details["reviews"],
            )

            ok, reason = self._passes_filters(item)
            if not ok:
                self.log(f"⛔ {username} — {reason}")
                return None

            self.seen_users.add(username)
            if url:
                self.seen_items.add(url)
            self.stats["valid"] += 1
            self.log(f"✅ {username} → {item.email}")
            return item

        except Exception:
            self.stats["errors"] += 1
            return None

    def stop(self):
        self.is_running = False
