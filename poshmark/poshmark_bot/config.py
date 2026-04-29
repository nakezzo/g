import os

BOT_TOKEN = "8763416260:AAEpYw1lpF3-14nVF7or3a73tLUP6FcP7gw"

SMTP_MAP = {
    "seznam.cz": "smtp.seznam.cz",
    "email.cz":  "smtp.seznam.cz",
    "post.cz":   "smtp.seznam.cz",
}
SMTP_PORT = 465

DATA_DIR = "userdata"

POSHMARK_CATEGORIES = {
    "women":       "/category/Women",
    "men":         "/category/Men",
    "kids":        "/category/Kids",
    "home":        "/category/Home",
    "pets":        "/category/Pets",
    "electronics": "/category/Electronics",
}

VVS_PLATFORMS = [
    "vinted","poshmark","etsy","depop","grailed","gumtree","mercari",
    "offerup","kijiji","kleinanzeigen","marktplaats","leboncoin","olx",
    "wallapop","subito","ricardo","finn","tori","dba","2dehands",
    "jofogas","bazaraki","adverts","tise","skelbiu","beebs","milanuncios",
    "marko","fiverr","quoka","laendleanzeiger",
]

_API_PARSERS = {
    "vvs":      {
        "name":  "VVS Project",
        "base":  "https://vvs.cx",
        "docs":  "https://telegra.ph/Dokumentaciya-API-03-18",
        "icon":  "🔵",
        "auth":  "api-key header",
    },
    "storm":    {
        "name":  "Storm Parser",
        "base":  "https://stormparser.lol",
        "docs":  "https://stormparser.lol/docs",
        "icon":  "⚡",
        "auth":  "Bearer token",
    },
    "xproject": {
        "name":  "xProject",
        "base":  "https://api.xproject.icu",
        "docs":  "https://api.xproject.icu/api/docs",
        "icon":  "🔴",
        "auth":  "X-API-Key header",
    },
}

_STARTTLS_ONLY = {"smtp-mail.outlook.com", "smtp.office365.com", "smtp.mail.me.com"}
_SSL_ONLY = set()

MAIN_TEXT = (
    "✦ <b>Poshmark Glinomesivo</b>\n"
    "<code>━━━━━━━━━━━━━━━━━━━━━━</code>\n"
    "акки грузи сука и шли\n\n"
    "▸ Выберите раздел:"
)

VAR_LABELS = {
    "sender": "👤 {sender} — Имя отправителя",
    "title":  "🏷 {title} — Заголовок",
    "text":   "📝 {text} — Текст письма",
    "button": "🔘 {button} — Кнопка",
    "link":   "🔗 {link} — Ссылка",
}
