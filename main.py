import os
import asyncio
import threading
import logging
import feedparser
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from flask import Flask
from flask_admin import Admin, AdminIndexView, expose
from flask_admin.contrib.sqla import ModelView
from flask_admin.form import SecureForm
from flask_sqlalchemy import SQLAlchemy
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from bs4 import BeautifulSoup
import re
import time

load_dotenv()

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------- Helper functions ----------
def clean_html(html_text):
    """تنظيف HTML وإرجاع نص نظيف"""
    if not html_text:
        return ""
    soup = BeautifulSoup(html_text, 'lxml')
    # حذف scripts و styles
    for script in soup(["script", "style"]):
        script.decompose()
    text = soup.get_text()
    # تنظيف المسافات الزائدة
    lines = (line.strip() for line in text.splitlines())
    chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
    text = ' '.join(chunk for chunk in chunks if chunk)
    return text

def is_arabic_text(text):
    """التحقق من وجود نص عربي وليس إنجليزي أو CAPTCHA"""
    if not text:
        return False
    
    # رسائل CAPTCHA والتحقق من البوت
    captcha_keywords = [
        'captcha', 'bot', 'proxy', 'network', 'unblock', 
        'malicious behavior', 'incident id', 'apologize for the inconvenience',
        'accessing site', 'solve this', 'request unblock'
    ]
    text_lower = text.lower()
    if any(keyword in text_lower for keyword in captcha_keywords):
        return False
    
    # البحث عن حروف عربية
    arabic_pattern = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+')
    arabic_chars = arabic_pattern.findall(text)
    
    # البحث عن حروف إنجليزية
    english_pattern = re.compile(r'[a-zA-Z]+')
    english_chars = english_pattern.findall(text)
    
    # حساب نسبة الأحرف العربية
    total_arabic = sum(len(word) for word in arabic_chars)
    total_english = sum(len(word) for word in english_chars)
    
    # يجب أن تكون نسبة العربي أكثر من 60% من النص
    if total_arabic == 0:
        return False
    
    if total_english > 0:
        arabic_ratio = total_arabic / (total_arabic + total_english)
        if arabic_ratio < 0.6:
            return False
    
    return True

def fetch_full_article(url):
    """جلب المقال الكامل من صفحة الخبر"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ar,en;q=0.9',
            'Referer': 'https://www.google.com/'
        }
        response = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.content, 'lxml')
        
        # إزالة العناصر غير المرغوبة
        for tag in soup(['script', 'style', 'nav', 'header', 'footer', 'aside', 'iframe', 'form', 'button', 'noscript']):
            tag.decompose()
        for class_name in ['share', 'social', 'advertisement', 'ad', 'ads', 'related', 'comments', 'sidebar', 'menu', 'navigation', 'tags', 'author', 'meta']:
            for element in soup.find_all(class_=lambda x: x and class_name in x.lower()):
                element.decompose()
        
        # البحث عن المحتوى الرئيسي بطرق متعددة
        content = None
        
        # الطريقة 1: البحث عن article tag
        if not content:
            article_tag = soup.find('article')
            if article_tag:
                content = article_tag
        
        # الطريقة 2: البحث عن div بـ id أو class تحتوي على كلمات رئيسية
        if not content:
            for keyword in ['article', 'content', 'post', 'entry', 'story', 'news', 'main', 'body', 'text', 'detail']:
                content = soup.find('div', id=lambda x: x and keyword in x.lower())
                if content:
                    break
                content = soup.find('div', class_=lambda x: x and keyword in x.lower())
                if content:
                    break
                content = soup.find('section', class_=lambda x: x and keyword in x.lower())
                if content:
                    break
        
        # الطريقة 3: البحث عن main tag
        if not content:
            main_tag = soup.find('main')
            if main_tag:
                content = main_tag
        
        # الطريقة 4: البحث عن p tags مباشرة من body
        if not content:
            body = soup.find('body')
            if body:
                paragraphs = body.find_all('p')
                if len(paragraphs) >= 3:
                    content = body
        
        if content:
            # جرب أولاً: استخراج كل النص مباشرة
            full_raw_text = content.get_text(separator='\n', strip=True)
            
            # تنظيف النص
            lines = [line.strip() for line in full_raw_text.split('\n') if line.strip()]
            clean_lines = []
            
            skip_keywords = [
                'اقرأ أيضا', 'شاهد أيضا', 'اشترك', 'تابع', 'انضم', 
                'للمزيد', 'إعلان', 'تابعنا', 'المصدر', 'اقرأ المزيد',
                'stories', 'دقيقة', 'فيديوهات', 'تاريخ النشر', 'pic.twitter',
                'GMT', '@', 'http', 'www.', 'loading', 'error', 'javascript'
            ]
            
            for line in lines:
                # تخطي السطور القصيرة جداً أو التي تحتوي على كلمات غير مرغوبة
                if len(line) > 25 and is_arabic_text(line):
                    line_lower = line.lower()
                    if not any(skip in line_lower for skip in skip_keywords):
                        if line not in clean_lines:  # تجنب التكرار
                            clean_lines.append(line)
            
            full_text = '\n\n'.join(clean_lines)
            
            # تأكد أن النص ليس قصيراً جداً وأنه عربي
            if full_text and len(full_text) > 200 and is_arabic_text(full_text):
                return full_text
        
        return None
    except Exception as e:
        logger.debug(f"خطأ في جلب المقال الكامل من {url}: {e}")
        return None

def extract_image_from_entry(entry):
    """استخراج رابط الصورة من RSS entry"""
    # entry من feedparser هو dict-like
    try:
        # محاولة 1: media_content
        media_content = entry.get('media_content') or entry.get('media:content')
        if media_content:
            # media_content يمكن تكون قائمة من dicts أو dict واحد
            if isinstance(media_content, (list, tuple)):
                for media in media_content:
                    url = media.get('url') or media.get('href')
                    if url:
                        return url
            elif isinstance(media_content, dict):
                url = media_content.get('url') or media_content.get('href')
                if url:
                    return url

        # محاولة 2: media_thumbnail
        media_thumbnail = entry.get('media_thumbnail') or entry.get('media:thumbnail')
        if media_thumbnail:
            if isinstance(media_thumbnail, (list, tuple)):
                for thumb in media_thumbnail:
                    url = thumb.get('url') or thumb.get('href')
                    if url:
                        return url
            elif isinstance(media_thumbnail, dict):
                url = media_thumbnail.get('url') or media_thumbnail.get('href')
                if url:
                    return url

        # محاولة 3: enclosures
        enclosures = entry.get('enclosures') or entry.get('links')
        if enclosures:
            if isinstance(enclosures, (list, tuple)):
                for enc in enclosures:
                    # enc عادة dict مع href و/or type
                    url = enc.get('href') or enc.get('url')
                    e_type = enc.get('type', '')
                    if url and e_type.startswith('image/'):
                        return url
                    if url and any(url.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']):
                        return url

        # محاولة 4: البحث في content عن img tag
        content_list = entry.get('content') or []
        if isinstance(content_list, (list, tuple)) and len(content_list) > 0:
            for c in content_list:
                value = c.get('value') if isinstance(c, dict) else c
                if value:
                    soup = BeautifulSoup(value, 'lxml')
                    img = soup.find('img')
                    if img and img.get('src'):
                        return img.get('src')

        # محاولة 5: البحث في description/summary عن img tag
        description = entry.get('description') or entry.get('summary') or ''
        if description:
            soup = BeautifulSoup(description, 'lxml')
            img = soup.find('img')
            if img and img.get('src'):
                return img.get('src')
    except Exception as e:
        logger.debug(f"خطأ في extract_image_from_entry: {e}")

    return None

def smart_truncate(text, max_length=None, with_image=True):
    """قطع النص بذكاء عند نهاية جملة كاملة

    Args:
        text: النص المراد قطعه
        max_length: الحد الأقصى المطلوب (سيتم ضبطه حسب حدود تيليجرام)
        with_image: هل النص سيرسل مع صورة (caption) أم بدون (رسالة عادية)

    Returns:
        النص المقطوع بشكل ذكي
    """
    if not text:
        return ""

    # حدود تيليجرام الرسمية
    TELEGRAM_CAPTION_LIMIT = 1024
    TELEGRAM_TEXT_LIMIT = 3850

    # إذا لم يعطى max_length، استخدم حدود تيليجرام المناسبة
    if not max_length or not isinstance(max_length, int):
        max_length = TELEGRAM_CAPTION_LIMIT if with_image else TELEGRAM_TEXT_LIMIT

    # لا تتجاوز الحدود الرسمية
    max_len = min(max_length, TELEGRAM_CAPTION_LIMIT if with_image else TELEGRAM_TEXT_LIMIT)

    if len(text) <= max_len:
        return text

    sentence_endings = ['. ', '؛ ', '! ', '? ', '؟ ', '.\n', '؛\n', '!\n', '?\n', '؟\n',
                        '." ', '.» ', '!" ', '!» ', '?" ', '?» ', '؟" ', '؟» ',
                        '.) ', '.] ', '!) ', '!] ', '?) ', '?] ', '؟) ', '؟] ']

    best_cut = -1
    best_ending_pos = -1

    for ending in sentence_endings:
        pos = text.rfind(ending, 0, max_len)
        if pos > best_ending_pos and pos >= 0:
            best_ending_pos = pos
            best_cut = pos + len(ending)

    if best_cut == -1:
        # حاول إيجاد الفراغ الأخير قبل الحد
        last_space = text.rfind(' ', 0, max_len)
        if last_space > 0:
            best_cut = last_space
        else:
            best_cut = max_len

    truncated = text[:best_cut].rstrip()

    if len(text) > best_cut:
        truncated += "..."

    return truncated

class Config:
    BOT_TOKEN = os.getenv('BOT_TOKEN')
    OWNER_ID = int(os.getenv('OWNER_ID', 0))
    DATABASE_URI = os.getenv('DATABASE_URI', 'sqlite:///gaza_news_bot.db')
    FLASK_SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'your-secret-key-change-this')
    FLASK_HOST = '0.0.0.0'
    FLASK_PORT = 5000
    FLASK_DEBUG = False

    NEWS_SOURCES = [
        {
            'name': 'فرانس 24 عربي',
            'url': 'https://www.france24.com/ar/rss',
            'keywords': ['غزة', 'فلسطين', 'إسرائيل', 'القدس']
        },
        {
            'name': 'عربي بوست',
            'url': 'https://arabicpost.net/feed/',
            'keywords': ['غزة', 'فلسطين', 'إسرائيل', 'القدس']
        },
        {
            'name': 'نون بوست',
            'url': 'https://www.noonpost.com/rss',
            'keywords': ['غزة', 'فلسطين', 'إسرائيل', 'القدس']
        },
        {
            'name': 'CNN عربية',
            'url': 'https://arabic.cnn.com/rss',
            'keywords': ['غزة', 'فلسطين', 'إسرائيل', 'القدس']
        },
        {
            'name': 'RT عربي',
            'url': 'https://arabic.rt.com/rss',
            'keywords': ['غزة', 'فلسطين', 'إسرائيل', 'القدس', 'حماس', 'الضفة']
        },
        {
            'name': 'BBC عربي',
            'url': 'https://feeds.bbci.co.uk/arabic/middle_east/rss.xml',
            'keywords': ['غزة', 'فلسطين', 'إسرائيل', 'القدس', 'حماس', 'الضفة']
        },
        {
            'name': 'العهد الإخبارية',
            'url': 'https://alahednews.com.lb/rss.xml',
            'keywords': ['غزة', 'فلسطين', 'إسرائيل', 'القدس']
        },
        {
            'name': 'المسيرة نت',
            'url': 'https://www.almasirah.net/rss.xml',
            'keywords': ['غزة', 'فلسطين', 'إسرائيل', 'القدس']
        },
        {
            'name': 'القدس العربي',
            'url': 'https://www.alquds.co.uk/feed/',
            'keywords': ['غزة', 'فلسطين', 'إسرائيل', 'القدس', 'حماس', 'الضفة']
        },
        {
            'name': 'عربي 21',
            'url': 'https://arabi21.com/rss.xml',
            'keywords': ['غزة', 'فلسطين', 'القدس']
        },
        {
            'name': 'الخليج أونلاين',
            'url': 'https://alkhaleejonline.net/rss.xml',
            'keywords': ['غزة', 'فلسطين', 'القدس']
        },
        {
            'name': 'الأناضول',
            'url': 'https://www.aa.com.tr/ar/rss/default?cat=arab-world',
            'keywords': ['غزة', 'فلسطين', 'القدس']
        },
        {
            'name': 'السبيل',
            'url': 'https://assabeel.net/rss',
            'keywords': ['غزة', 'فلسطين', 'القدس', 'حماس', 'إسرائيل']
        },
        {
            'name': 'الرؤيا',
            'url': 'https://royanews.tv/rss',
            'keywords': ['غزة', 'فلسطين', 'القدس', 'حماس', 'إسرائيل']
        },
        {
            'name': 'العربية نت',
            'url': 'https://www.alarabiya.net/rss.xml',
            'keywords': ['غزة', 'فلسطين', 'القدس', 'حماس', 'إسرائيل']
        },
        {
            'name': 'رأي اليوم',
            'url': 'https://www.raialyoum.com/feed/',
            'keywords': ['غزة', 'فلسطين', 'القدس', 'حماس']
        },
        {
            'name': 'الغد الأردنية',
            'url': 'https://alghad.com/feed/',
            'keywords': ['غزة', 'فلسطين', 'القدس', 'حماس', 'إسرائيل']
        },
        {
            'name': 'الشرق الأوسط',
            'url': 'https://aawsat.com/rss',
            'keywords': ['غزة', 'فلسطين', 'إسرائيل', 'القدس', 'حماس', 'الضفة']
        },
        {
            'name': 'العرب اللندنية',
            'url': 'https://alarab.co.uk/rss',
            'keywords': ['غزة', 'فلسطين', 'إسرائيل', 'القدس', 'حماس', 'الضفة']
        },
        {
            'name': 'الجزيرة نت',
            'url': 'https://www.aljazeera.net/xml/rss/all.xml',
            'keywords': ['غزة', 'فلسطين', 'إسرائيل', 'القدس', 'الضفة', 'حماس']
        },
        {
            'name': 'الميادين',
            'url': 'https://www.almayadeen.net/rss',
            'keywords': ['غزة', 'فلسطين', 'إسرائيل', 'القدس', 'حماس']
        },
        {
            'name': 'TRT عربي',
            'url': 'https://www.trtarabi.com/rss',
            'keywords': ['غزة', 'فلسطين', 'إسرائيل', 'القدس', 'حماس', 'الضفة']
        },
        {
            'name': 'الدستور الأردنية',
            'url': 'https://www.addustour.com/rss',
            'keywords': ['غزة', 'فلسطين', 'القدس', 'حماس', 'إسرائيل']
        },
        {
            'name': 'جو 24',
            'url': 'https://jo24.net/rss',
            'keywords': ['غزة', 'فلسطين', 'القدس', 'حماس', 'إسرائيل']
        },
    ]


    SCRAPE_INTERVAL_MINUTES = 0.166667
    MAX_NEWS_PER_FETCH = 200
    NEWS_EXPIRY_DAYS = 7
    PUBLISH_CHECK_INTERVAL_SECONDS = 240
    PUBLISH_BATCH_SIZE = 1
    SEND_DELAY_BETWEEN_CHANNELS = 3
    DELAY_BETWEEN_NEWS_POSTS = 40

    CHANNEL_ACTIVATION_MESSAGE = """
🔔 طلب تفعيل قناة جديدة

📢 القناة: {channel_title}
🆔 معرف القناة: {channel_id}
👤 المستخدم: {user_name}
🆔 معرف المستخدم: {user_id}

للموافقة: /approve {request_id}
للرفض: /reject {request_id}
"""

    ACTIVATION_APPROVED_MESSAGE = """
✅ تم تفعيل قناتك بنجاح!

سيتم نشر أخبار غزة وفلسطين تلقائياً في قناتك.
"""

    ACTIVATION_REJECTED_MESSAGE = """
❌ تم رفض طلب التفعيل.

يمكنك التواصل مع المالك للمزيد من المعلومات.
"""

# ---------- DB setup ----------
db = SQLAlchemy()

# نستخدم محرك مستقل + scoped_session للخلفيات (jobs) خارج Flask context
engine = create_engine(Config.DATABASE_URI, connect_args={"check_same_thread": False} if Config.DATABASE_URI.startswith("sqlite") else {})
SessionLocal = scoped_session(sessionmaker(bind=engine))
db_session = SessionLocal  # global session factory

# ---------- Models ----------
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=False, index=True)
    username = db.Column(db.String(255))
    first_name = db.Column(db.String(255))
    last_name = db.Column(db.String(255))
    is_owner = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_active = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<User {self.username or self.telegram_id}>'

class Channel(db.Model):
    __tablename__ = 'channels'
    id = db.Column(db.Integer, primary_key=True)
    telegram_id = db.Column(db.BigInteger, unique=True, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False)
    username = db.Column(db.String(255))
    is_active = db.Column(db.Boolean, default=False)
    added_by_user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    added_by = db.relationship('User', backref='channels_added')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_post_at = db.Column(db.DateTime)
    total_posts = db.Column(db.Integer, default=0)

    def __repr__(self):
        return f'<Channel {self.title}>'

class News(db.Model):
    __tablename__ = 'news'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.Text, nullable=False)
    link = db.Column(db.String(1024), unique=True, nullable=False, index=True)
    description = db.Column(db.Text)
    source = db.Column(db.String(255))
    published_date = db.Column(db.DateTime)
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_posted = db.Column(db.Boolean, default=False)
    image_url = db.Column(db.String(1024))
    clean_text = db.Column(db.Text)

    def __repr__(self):
        return f'<News {self.title[:50]}...>'

class ActivationRequest(db.Model):
    __tablename__ = 'activation_requests'
    id = db.Column(db.Integer, primary_key=True)
    channel_id = db.Column(db.Integer, db.ForeignKey('channels.id'), nullable=False)
    channel = db.relationship('Channel', backref='activation_requests')
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    user = db.relationship('User', foreign_keys=[user_id], backref='activation_requests')
    status = db.Column(db.String(50), default='pending')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.DateTime)
    resolved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    resolved_by = db.relationship('User', foreign_keys=[resolved_by_id], backref='resolved_requests')

    def __repr__(self):
        return f'<ActivationRequest {self.id} - {self.status}>'

class NewsPost(db.Model):
    __tablename__ = 'news_posts'
    id = db.Column(db.Integer, primary_key=True)
    news_id = db.Column(db.Integer, db.ForeignKey('news.id'), nullable=False)
    news = db.relationship('News', backref='posts')
    channel_id = db.Column(db.Integer, db.ForeignKey('channels.id'), nullable=False)
    channel = db.relationship('Channel', backref='news_posts')
    message_id = db.Column(db.BigInteger)
    posted_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<NewsPost {self.id}>'

class BotSettings(db.Model):
    __tablename__ = 'bot_settings'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text)
    description = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<BotSettings {self.key}>'

class BroadcastMessage(db.Model):
    __tablename__ = 'broadcast_messages'
    id = db.Column(db.Integer, primary_key=True)
    message_text = db.Column(db.Text, nullable=False)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    created_by = db.relationship('User', backref='broadcasts')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    sent_count = db.Column(db.Integer, default=0)
    failed_count = db.Column(db.Integer, default=0)
    status = db.Column(db.String(50), default='pending')

    def __repr__(self):
        return f'<BroadcastMessage {self.id}>'

# ---------- Scraper ----------
class NewsScraper:
    def __init__(self):
        self.sources = Config.NEWS_SOURCES
        self.max_news = Config.MAX_NEWS_PER_FETCH

    def is_relevant(self, title, description, keywords):
        text = f"{title} {description}".lower()
        return any(keyword.lower() in text for keyword in keywords)

    def parse_date(self, date_value):
        try:
            if not date_value:
                return datetime.utcnow()

            # إذا كان struct_time أو tuple-like من feedparser
            if hasattr(date_value, 'tm_year') or isinstance(date_value, (tuple, list)):
                try:
                    # تحويل struct_time إلى timestamp ثم إلى datetime
                    return datetime.fromtimestamp(time.mktime(date_value))
                except Exception:
                    # كحل احتياطي استخدم أول 6 عناصر إن أمكن
                    try:
                        parts = tuple(date_value)[:6]
                        return datetime(*parts)
                    except Exception:
                        return datetime.utcnow()

            # إذا كان نصًا، حاول عدة صيغ
            if isinstance(date_value, str):
                formats = [
                    '%a, %d %b %Y %H:%M:%S %Z',
                    '%Y-%m-%dT%H:%M:%SZ',
                    '%Y-%m-%d %H:%M:%S',
                    '%d %b %Y %H:%M:%S %Z'
                ]
                for fmt in formats:
                    try:
                        return datetime.strptime(date_value, fmt)
                    except Exception:
                        continue
                # كحل أخير، ارجع الآن
                return datetime.utcnow()

            if isinstance(date_value, datetime):
                return date_value

            return datetime.utcnow()
        except Exception:
            return datetime.utcnow()

    def fetch_rss_feed(self, source):
        session = db_session()
        try:
            feed = feedparser.parse(source['url'])
            added_count = 0
            
            logger.info(f"تم جلب {len(feed.entries)} مقالة من {source['name']}")

            for entry in feed.entries[:self.max_news]:
                title = entry.get('title', '') or ''
                description = entry.get('description', '') or entry.get('summary', '') or ''
                link = entry.get('link', '') or ''

                if not link:
                    logger.info(f"تخطي - لا يوجد رابط")
                    continue

                if not self.is_relevant(title, description, source['keywords']):
                    logger.info(f"تخطي - غير ذي صلة: {title[:50]}")
                    continue

                # فحص التكرار بناءً على الرابط
                existing = session.query(News).filter_by(link=link).first()
                if existing:
                    logger.info(f"تخطي - موجود مسبقاً: {title[:50]}")
                    continue
                
                # فحص إضافي: التحقق من العنوان لتجنب نفس الخبر برابط مختلف
                clean_title_check = clean_html(title)
                similar_news = session.query(News).filter(
                    News.title == clean_title_check,
                    News.source == source['name']
                ).first()
                if similar_news:
                    logger.info(f"تخطي - عنوان مكرر: {title[:50]}")
                    continue

                # تنظيف النص من HTML
                clean_title = clean_html(title)
                clean_desc = clean_html(description)
                
                # فلترة الأخبار العربية فقط
                combined_text = f"{clean_title} {clean_desc}"
                if not is_arabic_text(combined_text):
                    logger.info(f"تخطي - ليس عربي: {title[:50]}")
                    continue
                
                # التحقق من الحد الأدنى لطول الوصف (تجنب الأخبار المبتورة)
                if len(clean_desc) < 80:
                    logger.info(f"تخطي - وصف قصير جداً: {title[:50]}")
                    continue
                
                # استخراج الصورة
                image_url = extract_image_from_entry(entry)
                
                # جلب المقال الكامل من صفحة الخبر
                full_article = fetch_full_article(link)
                
                # إنشاء نص نظيف (استخدم المقال الكامل إذا توفر، وإلا استخدم الوصف)
                if full_article:
                    clean_text = f"{clean_title}\n\n{full_article}"
                else:
                    clean_text = f"{clean_title}\n\n{clean_desc}"
                
                # التحقق من الحد الأدنى للنص الكامل (300 حرف على الأقل)
                if len(clean_text) < 300:
                    logger.info(f"تخطي - نص قصير جداً ({len(clean_text)} حرف): {title[:50]}")
                    continue
                
                # التحقق النهائي من أن النص عربي
                if not is_arabic_text(clean_text):
                    logger.info(f"تخطي - النص النهائي ليس عربي: {title[:50]}")
                    continue

                published_date = self.parse_date(entry.get('published_parsed') or entry.get('published') or entry.get('updated_parsed') or entry.get('updated') or None)

                news_item = News(
                    title=clean_title,
                    link=link,
                    description=description,
                    source=source['name'],
                    published_date=published_date,
                    fetched_at=datetime.utcnow(),
                    image_url=image_url,
                    clean_text=clean_text
                )
                
                try:
                    session.add(news_item)
                    session.commit()
                    added_count += 1
                    logger.info(f"✅ تمت إضافة: {clean_title[:50]}")
                except Exception as e:
                    session.rollback()
                    if "UNIQUE constraint failed" not in str(e):
                        logger.error(f"خطأ في حفظ: {clean_title[:50]} - {str(e)}")

            return added_count
        except Exception as e:
            logger.error(f"خطأ في جلب الأخبار من {source['name']}: {str(e)}")
            session.rollback()
            return 0
        finally:
            session.close()

    def scrape_all_sources(self):
        total_added = 0
        for source in self.sources:
            logger.info(f"جلب الأخبار من: {source['name']}")
            added_count = self.fetch_rss_feed(source)
            total_added += added_count
        
        if total_added > 0:
            logger.info(f"✅ تم جمع {total_added} خبر جديد")
        else:
            logger.info("لا توجد أخبار جديدة")
        
        return total_added

    def clean_old_news(self):
        session = db_session()
        try:
            expiry_date = datetime.utcnow() - timedelta(days=Config.NEWS_EXPIRY_DAYS)
            old_news = session.query(News).filter(News.fetched_at < expiry_date).all()
            count = len(old_news)
            for news in old_news:
                session.delete(news)
            session.commit()
            logger.info(f"تم حذف {count} خبر قديم")
            return count
        except Exception as e:
            logger.error(f"خطأ في حذف الأخبار القديمة: {str(e)}")
            session.rollback()
            return 0
        finally:
            session.close()

    def get_unpublished_news(self, limit=15):
        session = db_session()
        try:
            items = session.query(News).filter_by(is_posted=False).order_by(News.published_date.desc()).limit(limit).all()
            return items
        finally:
            session.close()

    def mark_as_published(self, news_id):
        session = db_session()
        try:
            news = session.get(News, news_id)
            if news:
                news.is_posted = True
                session.commit()
        except Exception as e:
            logger.error(f"خطأ عند تعليم خبر كمُنشر: {str(e)}")
            session.rollback()
        finally:
            session.close()

    def mark_old_news_as_published(self):
        """تعليم الأخبار القديمة كمنشورة لتجنب نشرها دفعة واحدة عند التشغيل الأول"""
        session = db_session()
        try:
            # الأخبار التي عمرها أكثر من ساعة، علمها كمنشورة
            one_hour_ago = datetime.utcnow() - timedelta(hours=1)
            old_news = session.query(News).filter(
                News.is_posted == False,
                News.fetched_at < one_hour_ago
            ).all()
            
            count = len(old_news)
            for news in old_news:
                news.is_posted = True
            
            session.commit()
            if count > 0:
                logger.info(f"✅ تم تعليم {count} خبر قديم كمنشور")
            return count
        except Exception as e:
            logger.error(f"خطأ في تعليم الأخبار القديمة: {str(e)}")
            session.rollback()
            return 0
        finally:
            session.close()

# ---------- Bot command handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = db_session()
    try:
        db_user = session.query(User).filter_by(telegram_id=user.id).first()
        if not db_user:
            db_user = User(
                telegram_id=user.id,
                username=user.username,
                first_name=user.first_name,
                last_name=user.last_name,
                is_owner=(user.id == Config.OWNER_ID)
            )
            session.add(db_user)
            session.commit()
        else:
            db_user.last_active = datetime.utcnow()
            if user.id == Config.OWNER_ID and not db_user.is_owner:
                db_user.is_owner = True
            session.commit()

        welcome_message = f"""
مرحباً {user.first_name}! 👋

أنا بوت أخبار غزة وفلسطين 🇵🇸

💡 **كيف أعمل:**
- أقوم بجمع آخر الأخبار عن غزة وفلسطين من مصادر موثوقة
- يمكنك إضافتي لقناتك لنشر الأخبار تلقائياً

📢 **لإضافتي لقناتك:**
1. أضفني كمشرف في قناتك
2. أعطني صلاحية نشر الرسائل
3. استخدم الأمر /add_channel

🔧 **الأوامر المتاحة:**
/start - بدء المحادثة
/add_channel - إضافة قناة
/my_channels - قنواتي
/help - المساعدة
"""
        if db_user.is_owner:
            welcome_message += """
\n👑 **أوامر المالك:**
/stats - إحصائيات البوت
/approve <id> - الموافقة على طلب
/reject <id> - رفض طلب
/broadcast <رسالة> - إرسال رسالة جماعية
/pending - الطلبات المعلقة
"""
        await update.message.reply_text(welcome_message)
    finally:
        session.close()

# باقي handlers (add_channel, handle_channel_input, approve_request, reject_request, pending_requests,
# stats, broadcast, help_command, my_channels) — نعيد استخدام نفس المنهج: فتح session محلي وإغلاقه.
# لتوفير المساحة هنا أدرجت مثال start أعلاه، وسأعدل الباقي بنفس الطريقة أدناه:

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = db_session()
    try:
        db_user = session.query(User).filter_by(telegram_id=user.id).first()
        if not db_user:
            await update.message.reply_text("❌ خطأ! استخدم /start أولاً")
            return

        if db_user.is_banned:
            await update.message.reply_text("❌ تم حظرك من استخدام البوت")
            return

        instructions = """
📢 **خطوات إضافة القناة:**

1. أضفني كمشرف في قناتك
2. أعطني صلاحية "نشر الرسائل"
3. أرسل رابط القناة أو معرفها (@channel_username)

مثال: @GazaNewsChannel
"""
        await update.message.reply_text(instructions)
        context.user_data['waiting_for_channel'] = True
    finally:
        session.close()

async def handle_channel_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get('waiting_for_channel'):
        return

    channel_input = update.message.text.strip()
    user = update.effective_user
    session = db_session()
    try:
        try:
            chat = await context.bot.get_chat(channel_input)
            admins = await context.bot.get_chat_administrators(chat.id)
            bot_is_admin = any(admin.user.id == context.bot.id for admin in admins)

            if not bot_is_admin:
                await update.message.reply_text("❌ البوت ليس مشرفاً في هذه القناة!")
                return

            bot_admin = next((admin for admin in admins if admin.user.id == context.bot.id), None)
            if not bot_admin or not getattr(bot_admin, "can_post_messages", True):
                await update.message.reply_text("❌ البوت لا يملك صلاحية نشر الرسائل!")
                return

            db_user = session.query(User).filter_by(telegram_id=user.id).first()
            channel = session.query(Channel).filter_by(telegram_id=chat.id).first()

            if not channel:
                channel = Channel(
                    telegram_id=chat.id,
                    title=getattr(chat, 'title', str(chat.id)),
                    username=getattr(chat, 'username', None),
                    added_by_user_id=db_user.id
                )
                session.add(channel)
                session.commit()

            existing_request = session.query(ActivationRequest).filter_by(
                channel_id=channel.id,
                status='pending'
            ).first()

            if existing_request:
                await update.message.reply_text("⏳ لديك طلب معلق بالفعل لهذه القناة")
                return

            request = ActivationRequest(
                channel_id=channel.id,
                user_id=db_user.id,
                status='pending'
            )
            session.add(request)
            session.commit()

            owner = session.query(User).filter_by(is_owner=True).first()
            if owner:
                notification = Config.CHANNEL_ACTIVATION_MESSAGE.format(
                    channel_title=chat.title,
                    channel_id=chat.id,
                    user_name=user.first_name,
                    user_id=user.id,
                    request_id=request.id
                )
                try:
                    await context.bot.send_message(owner.telegram_id, notification)
                except Exception as e:
                    logger.error(f"لا يمكن إرسال إشعار للمالك: {e}")

            await update.message.reply_text(
                f"✅ تم إرسال طلب التفعيل للمالك\n\n"
                f"📢 القناة: {chat.title}\n"
                f"⏳ الحالة: قيد المراجعة"
            )
            context.user_data['waiting_for_channel'] = False
        except Exception as e:
            logger.error(f"خطأ في إضافة القناة: {str(e)}")
            await update.message.reply_text(f"❌ خطأ: {str(e)}")
    finally:
        session.close()

# الموافقة/الرفض/عرض الطلبات والإحصائيات والبث تستخدم نفس نمط الجلسة:
async def approve_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = db_session()
    try:
        db_user = session.query(User).filter_by(telegram_id=user.id).first()
        if not db_user or not db_user.is_owner:
            await update.message.reply_text("❌ هذا الأمر للمالك فقط")
            return

        if not context.args:
            await update.message.reply_text("❌ استخدم: /approve <request_id>")
            return

        try:
            request_id = int(context.args[0])
            request = session.get(ActivationRequest, request_id)
            if not request:
                await update.message.reply_text("❌ الطلب غير موجود")
                return

            if request.status != 'pending':
                await update.message.reply_text(f"❌ الطلب تم {request.status} مسبقاً")
                return

            request.status = 'approved'
            request.resolved_at = datetime.utcnow()
            request.resolved_by_id = db_user.id
            request.channel.is_active = True
            session.commit()

            try:
                await context.bot.send_message(
                    request.user.telegram_id,
                    Config.ACTIVATION_APPROVED_MESSAGE
                )
            except Exception as e:
                logger.error(f"خطأ في إرسال رسالة قبول للطالب: {e}")

            await update.message.reply_text(f"✅ تم تفعيل القناة: {request.channel.title}")
        except ValueError:
            await update.message.reply_text("❌ معرف الطلب يجب أن يكون رقم")
    finally:
        session.close()

async def reject_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = db_session()
    try:
        db_user = session.query(User).filter_by(telegram_id=user.id).first()
        if not db_user or not db_user.is_owner:
            await update.message.reply_text("❌ هذا الأمر للمالك فقط")
            return

        if not context.args:
            await update.message.reply_text("❌ استخدم: /reject <request_id>")
            return

        try:
            request_id = int(context.args[0])
            request = session.get(ActivationRequest, request_id)
            if not request:
                await update.message.reply_text("❌ الطلب غير موجود")
                return

            if request.status != 'pending':
                await update.message.reply_text(f"❌ الطلب تم {request.status} مسبقاً")
                return

            request.status = 'rejected'
            request.resolved_at = datetime.utcnow()
            request.resolved_by_id = db_user.id
            session.commit()

            try:
                await context.bot.send_message(
                    request.user.telegram_id,
                    Config.ACTIVATION_REJECTED_MESSAGE
                )
            except Exception as e:
                logger.error(f"خطأ في إرسال رسالة رفض للطالب: {e}")

            await update.message.reply_text(f"❌ تم رفض الطلب للقناة: {request.channel.title}")
        except ValueError:
            await update.message.reply_text("❌ معرف الطلب يجب أن يكون رقم")
    finally:
        session.close()

async def pending_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = db_session()
    try:
        db_user = session.query(User).filter_by(telegram_id=user.id).first()
        if not db_user or not db_user.is_owner:
            await update.message.reply_text("❌ هذا الأمر للمالك فقط")
            return

        requests = session.query(ActivationRequest).filter_by(status='pending').all()
        if not requests:
            await update.message.reply_text("✅ لا توجد طلبات معلقة")
            return

        message = "⏳ **الطلبات المعلقة:**\n\n"
        for req in requests:
            message += f"🆔 #{req.id}\n"
            message += f"📢 القناة: {req.channel.title}\n"
            message += f"👤 المستخدم: {req.user.first_name}\n"
            message += f"📅 التاريخ: {req.created_at.strftime('%Y-%m-%d %H:%M')}\n"
            message += f"✅ /approve {req.id}\n"
            message += f"❌ /reject {req.id}\n\n"

        await update.message.reply_text(message)
    finally:
        session.close()

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = db_session()
    try:
        db_user = session.query(User).filter_by(telegram_id=user.id).first()
        if not db_user or not db_user.is_owner:
            await update.message.reply_text("❌ هذا الأمر للمالك فقط")
            return

        total_users = session.query(User).count()
        total_channels = session.query(Channel).count()
        active_channels = session.query(Channel).filter_by(is_active=True).count()
        total_news = session.query(News).count()
        total_posts = session.query(NewsPost).count()
        pending = session.query(ActivationRequest).filter_by(status='pending').count()

        stats_message = f"""
📊 **إحصائيات البوت:**

👥 المستخدمون: {total_users}
📢 القنوات الكلية: {total_channels}
✅ القنوات المفعلة: {active_channels}
📰 الأخبار المحفوظة: {total_news}
📤 المنشورات: {total_posts}
⏳ الطلبات المعلقة: {pending}
"""
        await update.message.reply_text(stats_message)
    finally:
        session.close()

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = db_session()
    try:
        db_user = session.query(User).filter_by(telegram_id=user.id).first()
        if not db_user or not db_user.is_owner:
            await update.message.reply_text("❌ هذا الأمر للمالك فقط")
            return

        if not context.args:
            await update.message.reply_text("❌ استخدم: /broadcast <رسالة>")
            return

        message_text = ' '.join(context.args)
        broadcast_msg = BroadcastMessage(
            message_text=message_text,
            created_by_id=db_user.id,
            status='sending'
        )
        session.add(broadcast_msg)
        session.commit()

        users = session.query(User).filter_by(is_banned=False).all()
        sent = 0
        failed = 0

        for u in users:
            try:
                await context.bot.send_message(u.telegram_id, message_text)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1

        broadcast_msg.sent_count = sent
        broadcast_msg.failed_count = failed
        broadcast_msg.status = 'completed'
        session.commit()

        await update.message.reply_text(
            f"✅ تم الإرسال\n\n"
            f"✔️ نجح: {sent}\n"
            f"❌ فشل: {failed}"
        )
    finally:
        session.close()

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = """
🆘 **المساعدة:**

**للمستخدمين:**
/start - بدء المحادثة
/add_channel - إضافة قناة
/my_channels - قنواتي
/help - المساعدة

📢 سيتم نشر أخبار غزة وفلسطين تلقائياً بعد الموافقة
"""
    await update.message.reply_text(help_text)

async def my_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    session = db_session()
    try:
        db_user = session.query(User).filter_by(telegram_id=user.id).first()
        if not db_user:
            await update.message.reply_text("❌ استخدم /start أولاً")
            return

        channels = session.query(Channel).filter_by(added_by_user_id=db_user.id).all()
        if not channels:
            await update.message.reply_text("📢 ليس لديك قنوات مضافة")
            return

        message = "📢 **قنواتك:**\n\n"
        for ch in channels:
            status = "✅ مفعلة" if ch.is_active else "⏳ قيد المراجعة"
            message += f"• {ch.title}\n"
            message += f"  الحالة: {status}\n"
            message += f"  المنشورات: {ch.total_posts}\n\n"

        await update.message.reply_text(message)
    finally:
        session.close()

async def handle_forwarded_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    message = update.message
    
    session = db_session()
    try:
        db_user = session.query(User).filter_by(telegram_id=user.id).first()
        if not db_user or not db_user.is_owner:
            return
        
        if message.forward_from_chat or message.forward_from:
            text_content = message.text or message.caption or ""
            
            if text_content:
                found_news = session.query(News).filter(
                    News.clean_text.contains(text_content[:100])
                ).first()
                
                if not found_news:
                    found_news = session.query(News).filter(
                        News.title.contains(text_content[:50])
                    ).first()
                
                if found_news:
                    channel_name = ""
                    if message.forward_from_chat:
                        channel_name = f"\nالمحول من: {message.forward_from_chat.title}"
                    
                    await update.message.reply_text(
                        f"📰 المصدر: {found_news.source}{channel_name}"
                    )
                else:
                    await update.message.reply_text(
                        "❌ لم أتمكن من التعرف على مصدر هذا الخبر في قاعدة البيانات"
                    )
    finally:
        session.close()

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    user = update.effective_user
    session = db_session()
    try:
        db_user = session.query(User).filter_by(telegram_id=user.id).first()
        if not db_user or not db_user.is_owner:
            await update.message.reply_text("❌ هذا الأمر للمالك فقط")
            return

        total_users = session.query(User).count()
        total_channels = session.query(Channel).count()
        active_channels = session.query(Channel).filter_by(is_active=True).count()
        total_news = session.query(News).count()
        unpublished_news = session.query(News).filter_by(is_posted=False).count()
        pending_requests = session.query(ActivationRequest).filter_by(status='pending').count()

        keyboard = [
            [
                InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats"),
                InlineKeyboardButton("📢 القنوات", callback_data="admin_channels")
            ],
            [
                InlineKeyboardButton("📰 الأخبار", callback_data="admin_news"),
                InlineKeyboardButton("⏳ الطلبات المعلقة", callback_data="admin_pending")
            ],
            [
                InlineKeyboardButton("👥 المستخدمون", callback_data="admin_users"),
                InlineKeyboardButton("🔄 تحديث", callback_data="admin_refresh")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        message = f"""
🎛️ **لوحة تحكم البوت**

👥 المستخدمون: {total_users}
📢 القنوات: {active_channels}/{total_channels}
📰 الأخبار: {unpublished_news}/{total_news} (غير منشورة)
⏳ الطلبات المعلقة: {pending_requests}

اختر القسم الذي تريد الوصول إليه:
"""
        await update.message.reply_text(message, reply_markup=reply_markup)
    finally:
        session.close()

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    session = db_session()
    try:
        db_user = session.query(User).filter_by(telegram_id=user.id).first()
        if not db_user or not db_user.is_owner:
            await query.edit_message_text("❌ هذا الأمر للمالك فقط")
            return

        if query.data == "admin_stats":
            total_users = session.query(User).count()
            total_channels = session.query(Channel).count()
            active_channels = session.query(Channel).filter_by(is_active=True).count()
            total_news = session.query(News).count()
            unpublished_news = session.query(News).filter_by(is_posted=False).count()
            total_posts = session.query(NewsPost).count()
            
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = f"""
📊 **إحصائيات مفصلة:**

👥 المستخدمون: {total_users}
📢 القنوات الكلية: {total_channels}
✅ القنوات المفعلة: {active_channels}
📰 الأخبار المحفوظة: {total_news}
🆕 الأخبار غير المنشورة: {unpublished_news}
📤 المنشورات: {total_posts}
"""
            await query.edit_message_text(message, reply_markup=reply_markup)
        
        elif query.data == "admin_channels":
            channels = session.query(Channel).filter_by(is_active=True).limit(10).all()
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = "📢 **القنوات المفعلة:**\n\n"
            if channels:
                for ch in channels:
                    message += f"• {ch.title}\n  المنشورات: {ch.total_posts}\n\n"
            else:
                message += "لا توجد قنوات مفعلة\n"
            
            await query.edit_message_text(message, reply_markup=reply_markup)
        
        elif query.data == "admin_news":
            unpublished = session.query(News).filter_by(is_posted=False).limit(5).all()
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = "📰 **آخر الأخبار غير المنشورة:**\n\n"
            if unpublished:
                for news in unpublished:
                    message += f"• {news.title[:50]}...\n  المصدر: {news.source}\n\n"
            else:
                message += "لا توجد أخبار غير منشورة\n"
            
            await query.edit_message_text(message, reply_markup=reply_markup)
        
        elif query.data == "admin_pending":
            requests = session.query(ActivationRequest).filter_by(status='pending').limit(5).all()
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = "⏳ **الطلبات المعلقة:**\n\n"
            if requests:
                for req in requests:
                    message += f"🆔 #{req.id}\n"
                    message += f"📢 القناة: {req.channel.title}\n"
                    message += f"👤 المستخدم: {req.user.first_name}\n"
                    message += f"✅ /approve {req.id}\n"
                    message += f"❌ /reject {req.id}\n\n"
            else:
                message += "لا توجد طلبات معلقة\n"
            
            await query.edit_message_text(message, reply_markup=reply_markup)
        
        elif query.data == "admin_users":
            users = session.query(User).order_by(User.created_at.desc()).limit(10).all()
            keyboard = [[InlineKeyboardButton("🔙 رجوع", callback_data="admin_back")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            message = "👥 **آخر المستخدمين:**\n\n"
            for user_obj in users:
                message += f"• {user_obj.first_name or 'بدون اسم'}\n  @{user_obj.username or 'بدون معرف'}\n\n"
            
            await query.edit_message_text(message, reply_markup=reply_markup)
        
        elif query.data == "admin_refresh" or query.data == "admin_back":
            total_users = session.query(User).count()
            total_channels = session.query(Channel).count()
            active_channels = session.query(Channel).filter_by(is_active=True).count()
            total_news = session.query(News).count()
            unpublished_news = session.query(News).filter_by(is_posted=False).count()
            pending_requests = session.query(ActivationRequest).filter_by(status='pending').count()

            keyboard = [
                [
                    InlineKeyboardButton("📊 الإحصائيات", callback_data="admin_stats"),
                    InlineKeyboardButton("📢 القنوات", callback_data="admin_channels")
                ],
                [
                    InlineKeyboardButton("📰 الأخبار", callback_data="admin_news"),
                    InlineKeyboardButton("⏳ الطلبات المعلقة", callback_data="admin_pending")
                ],
                [
                    InlineKeyboardButton("👥 المستخدمون", callback_data="admin_users"),
                    InlineKeyboardButton("🔄 تحديث", callback_data="admin_refresh")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            message = f"""
🎛️ **لوحة تحكم البوت**

👥 المستخدمون: {total_users}
📢 القنوات: {active_channels}/{total_channels}
📰 الأخبار: {unpublished_news}/{total_news} (غير منشورة)
⏳ الطلبات المعلقة: {pending_requests}

اختر القسم الذي تريد الوصول إليه:
"""
            await query.edit_message_text(message, reply_markup=reply_markup)
    finally:
        session.close()

# ---------- Bot & scheduler setup ----------
def setup_bot():
    from telegram.ext import CallbackQueryHandler
    application = Application.builder().token(Config.BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("add_channel", add_channel))
    application.add_handler(CommandHandler("approve", approve_request))
    application.add_handler(CommandHandler("reject", reject_request))
    application.add_handler(CommandHandler("pending", pending_requests))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("my_channels", my_channels))
    application.add_handler(CommandHandler("admin", admin_panel))
    application.add_handler(CallbackQueryHandler(admin_callback, pattern="^admin_"))
    application.add_handler(MessageHandler(filters.FORWARDED & ~filters.COMMAND, handle_forwarded_message))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_channel_input))
    return application

async def publish_news_to_channels(application):
    scraper = NewsScraper()
    unpublished = scraper.get_unpublished_news(limit=Config.PUBLISH_BATCH_SIZE)
    if not unpublished:
        return

    session = db_session()
    try:
        active_channels = session.query(Channel).filter_by(is_active=True).all()
    finally:
        session.close()

    for news_index, news in enumerate(unpublished):
        base_text = news.clean_text or f"{news.title}\n\n{clean_html(news.description or '')}"
        has_image = bool(news.image_url)
        
        # قص النص بذكاء حسب ما إذا كان هناك صورة أم لا
        # نستخدم with_image=False لأننا نرسل النص كرسالة منفصلة حتى مع الصورة
        truncated_text = smart_truncate(base_text, with_image=False)
        
        full_text = truncated_text
        
        # تسجيل معلومات الخبر المنشور
        is_truncated = len(base_text) > len(truncated_text)
        logger.info(f"""
╔═══════════════════════════════════════════════════════════
║ 📰 خبر جديد منشور
╠═══════════════════════════════════════════════════════════
║ العنوان: {news.title[:100]}
║ المصدر: {news.source}
║ الرابط: {news.link}
║ طول النص الأصلي: {len(base_text)} حرف
║ طول النص المنشور: {len(truncated_text)} حرف
║ تم القص: {"نعم ✂️" if is_truncated else "لا ✓"}
║ يحتوي صورة: {"نعم 🖼️" if has_image else "لا"}
╚═══════════════════════════════════════════════════════════
        """)
        
        for channel in active_channels:
            try:
                if has_image:
                    # إرسال الصورة أولاً
                    await application.bot.send_photo(
                        chat_id=channel.telegram_id,
                        photo=news.image_url
                    )
                    # ثم إرسال النص الكامل كرسالة منفصلة
                    sent_msg = await application.bot.send_message(
                        chat_id=channel.telegram_id,
                        text=full_text
                    )
                else:
                    # إرسال النص الكامل مباشرة
                    sent_msg = await application.bot.send_message(
                        chat_id=channel.telegram_id,
                        text=full_text
                    )
                
                session = db_session()
                try:
                    post = NewsPost(
                        news_id=news.id,
                        channel_id=channel.id,
                        message_id=sent_msg.message_id
                    )
                    session.add(post)
                    ch = session.get(Channel, channel.id)
                    if ch:
                        ch.total_posts = (ch.total_posts or 0) + 1
                        ch.last_post_at = datetime.utcnow()
                    session.commit()
                except Exception as e:
                    logger.error(f"خطأ في حفظ NewsPost: {e}")
                    session.rollback()
                finally:
                    session.close()

                await asyncio.sleep(Config.SEND_DELAY_BETWEEN_CHANNELS)
            except Exception as e:
                logger.error(f"خطأ في النشر للقناة {channel.title}: {str(e)}")

        # تعليم الخبر كمنشور بعد إرساله لجميع القنوات
        session_mark = db_session()
        try:
            news_to_mark = session_mark.get(News, news.id)
            if news_to_mark and not news_to_mark.is_posted:
                news_to_mark.is_posted = True
                session_mark.commit()
                logger.info(f"✅ تم تعليم الخبر كمنشور: {news.title[:50]}")
        except Exception as e:
            logger.error(f"خطأ عند تعليم الخبر كمُنشر: {e}")
            session_mark.rollback()
        finally:
            session_mark.close()
        
        if news_index < len(unpublished) - 1:
            await asyncio.sleep(Config.DELAY_BETWEEN_NEWS_POSTS)

async def publisher_job(context: ContextTypes.DEFAULT_TYPE):
    # وظيفة تنشر الأخبار الجديدة
    try:
        await publish_news_to_channels(context.application)
    except Exception as e:
        logger.error(f"خطأ في وظيفة النشر: {e}")

class SecureModelView(ModelView):
    form_base_class = SecureForm
    can_export = True
    def is_accessible(self):
        return True

class DashboardView(AdminIndexView):
    @expose('/')
    def index(self):
        total_users = User.query.count()
        total_channels = Channel.query.count()
        active_channels = Channel.query.filter_by(is_active=True).count()
        total_news = News.query.count()
        unpublished_news = News.query.filter_by(is_posted=False).count()
        pending_requests = ActivationRequest.query.filter_by(status='pending').count()

        stats_html = f"""
<h1>📊 لوحة التحكم الرئيسية</h1>
<div style="display: flex; gap: 20px; flex-wrap: wrap;">
    <div style="background: #e3f2fd; padding: 20px; border-radius: 8px; flex: 1; min-width: 200px;">
        <h3>👥 المستخدمون</h3>
        <h2>{total_users}</h2>
    </div>
    <div style="background: #e8f5e9; padding: 20px; border-radius: 8px; flex: 1; min-width: 200px;">
        <h3>📢 القنوات المفعلة</h3>
        <h2>{active_channels}/{total_channels}</h2>
    </div>
    <div style="background: #fff3e0; padding: 20px; border-radius: 8px; flex: 1; min-width: 200px;">
        <h3>📰 الأخبار غير المنشورة</h3>
        <h2>{unpublished_news}/{total_news}</h2>
    </div>
    <div style="background: #fce4ec; padding: 20px; border-radius: 8px; flex: 1; min-width: 200px;">
        <h3>⏳ الطلبات المعلقة</h3>
        <h2>{pending_requests}</h2>
    </div>
</div>
<div style="margin-top: 30px; padding: 20px; background: #f5f5f5; border-radius: 8px;">
    <h3>🎯 الميزات الرئيسية:</h3>
    <ul>
        <li>إدارة المستخدمين والقنوات</li>
        <li>جمع الأخبار من مصادر متعددة</li>
        <li>نشر تلقائي للقنوات المفعلة</li>
        <li>نظام موافقة طلبات التفعيل</li>
        <li>إرسال رسائل جماعية</li>
    </ul>
</div>
"""
        return stats_html

def create_admin_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = Config.FLASK_SECRET_KEY
    app.config['SQLALCHEMY_DATABASE_URI'] = Config.DATABASE_URI
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)

    admin = Admin(app, name='لوحة تحكم بوت أخبار غزة', template_mode='bootstrap4', index_view=DashboardView(), url='/admin')
    admin.add_view(SecureModelView(User, db.session, name='المستخدمون'))
    admin.add_view(SecureModelView(Channel, db.session, name='القنوات'))
    admin.add_view(SecureModelView(News, db.session, name='الأخبار'))
    admin.add_view(SecureModelView(ActivationRequest, db.session, name='طلبات التفعيل'))
    admin.add_view(SecureModelView(NewsPost, db.session, name='المنشورات'))
    admin.add_view(SecureModelView(BotSettings, db.session, name='الإعدادات'))
    admin.add_view(SecureModelView(BroadcastMessage, db.session, name='الرسائل الجماعية'))
    
    @app.route('/')
    def index():
        from flask import redirect
        return redirect('/admin')

    return app

def init_database(app):
    logger.info("تهيئة قاعدة البيانات...")
    # إنشاء الجداول باستخدام نفس محرك SQLAlchemy
    with app.app_context():
        db.create_all()
    db.metadata.create_all(engine)
    logger.info("✅ تم تهيئة قاعدة البيانات بنجاح")

def scrape_news_job():
    logger.info("🔍 بدء جمع الأخبار...")
    try:
        scraper = NewsScraper()
        count = scraper.scrape_all_sources()
        logger.info(f"✅ تم جمع {count} خبر جديد")
        
        # تعليم الأخبار القديمة كمنشورة لتجنب نشرها دفعة واحدة
        scraper.mark_old_news_as_published()
        
        # تم تعطيل حذف الأخبار القديمة - الأخبار ستستمر في الزيادة بدون حذف
        # scraper.clean_old_news()
    except Exception as e:
        logger.error(f"❌ خطأ في جمع الأخبار: {str(e)}")

def run_telegram_bot():
    logger.info("🤖 بدء تشغيل البوت...")

    if not Config.BOT_TOKEN:
        logger.error("❌ BOT_TOKEN غير موجود")
        return

    if not Config.OWNER_ID or Config.OWNER_ID == 0:
        logger.error("❌ OWNER_ID غير موجود")
        return

    application = setup_bot()

    # إضافة وظيفة نشر الأخبار كل فترة محددة
    application.job_queue.run_repeating(
        publisher_job, 
        interval=Config.PUBLISH_CHECK_INTERVAL_SECONDS, 
        first=5
    )
    logger.info(f"✅ نظام النشر يعمل (كل {Config.PUBLISH_CHECK_INTERVAL_SECONDS} ثانية)")

    scheduler = BackgroundScheduler()
    scheduler.add_job(scrape_news_job, 'interval', minutes=Config.SCRAPE_INTERVAL_MINUTES, next_run_time=datetime.now())
    scheduler.start()
    logger.info("✅ المجدول يعمل بنجاح")

    logger.info("✅ البوت جاهز للعمل!")
    application.run_polling(drop_pending_updates=False, allowed_updates=Update.ALL_TYPES)

def main():
    logger.info("=" * 50)
    logger.info("🇵🇸 بوت أخبار غزة وفلسطين")
    logger.info("=" * 50)
    app = create_admin_app()
    init_database(app)
    flask_thread = threading.Thread(target=lambda: app.run(host=Config.FLASK_HOST, port=Config.FLASK_PORT, debug=Config.FLASK_DEBUG, use_reloader=False), daemon=True)
    flask_thread.start()
    logger.info(f"✅ لوحة التحكم تعمل على http://{Config.FLASK_HOST}:{Config.FLASK_PORT}")
    run_telegram_bot()

if __name__ == "__main__":
    main()
