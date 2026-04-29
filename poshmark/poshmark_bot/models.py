from dataclasses import dataclass

@dataclass
class Account:
    email: str
    password: str
    enabled: bool = True
    sent_count: int = 0
    error_count: int = 0
    last_error: str = ""
    send_limit: int = 0

@dataclass
class SentLog:
    from_email: str
    to_email: str
    subject: str
    status: str
    timestamp: str
    error: str = ""

@dataclass
class PoshmarkItem:
    username: str
    email: str
    item_title: str
    item_url: str
    sold_count: str = ""
    price: str = ""
    listings_count: str = ""
    reviews_count: str = ""
