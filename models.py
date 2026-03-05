from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from typing import Optional, List, Dict, Any
from datetime import datetime

# Сначала создаём объект db
db = SQLAlchemy()

class User(db.Model, UserMixin):
    """Пользователи сайта"""
    __tablename__ = 'user'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    discord_id = db.Column(db.String(50), nullable=True)
    discord_avatar = db.Column(db.String(256), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class BotDatabase:
    """Класс для подключения к БД Discord бота"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn: Optional[sqlite3.Connection] = None
    
    def connect(self) -> bool:
        """Подключение к базе данных бота"""
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            return True
        except Exception as e:
            print(f"Ошибка подключения к БД бота: {e}")
            return False
    
    def close(self):
        """Закрытие подключения"""
        if self.conn:
            self.conn.close()
            self.conn = None
    
    # --- Статистика ---
    def get_server_count(self) -> int:
        """Количество серверов"""
        if not self.conn:
            return 0
        try:
            cursor = self.conn.execute("SELECT COUNT(DISTINCT guild_id) FROM guilds")
            result = cursor.fetchone()
            return result[0] if result else 0
        except:
            return 0
    
    def get_user_count(self) -> int:
        """Количество пользователей"""
        if not self.conn:
            return 0
        try:
            cursor = self.conn.execute("SELECT COUNT(DISTINCT user_id) FROM members")
            result = cursor.fetchone()
            return result[0] if result else 0
        except:
            return 0
    
    def get_message_count(self) -> int:
        """Общее количество сообщений"""
        if not self.conn:
            return 0
        try:
            cursor = self.conn.execute("SELECT SUM(total_messages) FROM members")
            result = cursor.fetchone()
            return result[0] if result and result[0] else 0
        except:
            return 0
    
    def get_quote_count(self) -> int:
        """Количество цитат"""
        if not self.conn:
            return 0
        try:
            cursor = self.conn.execute("SELECT COUNT(*) FROM quotes")
            result = cursor.fetchone()
            return result[0] if result else 0
        except:
            return 0
    
    # --- Статистика по дням для графиков ---
    def get_stats_by_date(self, days: int = 7) -> List[Dict[str, Any]]:
        """Получить статистику сообщений по дням"""
        if not self.conn:
            return []
        try:
            cursor = self.conn.execute('''
                SELECT date, SUM(count) as total
                FROM message_stats
                WHERE date >= date('now', ?)
                GROUP BY date
                ORDER BY date ASC
            ''', (f'-{days} days',))
            return [dict(row) for row in cursor.fetchall()]
        except:
            return []
    
    def get_voice_stats_by_date(self, days: int = 7) -> List[Dict[str, Any]]:
        """Получить статистику голосового времени по дням"""
        if not self.conn:
            return []
        try:
            cursor = self.conn.execute('''
                SELECT date, SUM(seconds) as total
                FROM voice_stats
                WHERE date >= date('now', ?)
                GROUP BY date
                ORDER BY date ASC
            ''', (f'-{days} days',))
            return [dict(row) for row in cursor.fetchall()]
        except:
            return []
    
    def get_xp_distribution(self) -> List[Dict[str, Any]]:
        """Распределение пользователей по уровням XP"""
        if not self.conn:
            return []
        try:
            cursor = self.conn.execute('''
                SELECT 
                    CASE 
                        WHEN xp < 100 THEN '0-100'
                        WHEN xp < 500 THEN '100-500'
                        WHEN xp < 1000 THEN '500-1000'
                        WHEN xp < 5000 THEN '1000-5000'
                        ELSE '5000+'
                    END as range,
                    COUNT(*) as count
                FROM members
                GROUP BY range
            ''')
            return [dict(row) for row in cursor.fetchall()]
        except:
            return []
    
    # --- Пользователи ---
    def get_top_users(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Топ пользователей по XP"""
        if not self.conn:
            return []
        try:
            cursor = self.conn.execute('''
                SELECT user_id, xp, total_messages, voice_seconds
                FROM members
                ORDER BY xp DESC
                LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]
        except:
            return []
    
    def get_all_guilds(self) -> List[Dict[str, Any]]:
        """Все сервера"""
        if not self.conn:
            return []
        try:
            cursor = self.conn.execute("SELECT * FROM guilds")
            return [dict(row) for row in cursor.fetchall()]
        except:
            return []
    
    def get_all_quotes(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Последние цитаты"""
        if not self.conn:
            return []
        try:
            cursor = self.conn.execute('''
                SELECT id, guild_id, author_id, text, created_at
                FROM quotes
                ORDER BY created_at DESC
                LIMIT ?
            ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]
        except:
            return []
    
    def get_guild_stats(self, guild_id: int) -> Dict[str, Any]:
        """Статистика конкретного сервера"""
        if not self.conn:
            return {}
        try:
            cursor = self.conn.execute('''
                SELECT 
                    COUNT(DISTINCT user_id) as user_count,
                    SUM(total_messages) as total_messages,
                    SUM(xp) as total_xp
                FROM members
                WHERE guild_id = ?
            ''', (guild_id,))
            result = cursor.fetchone()
            return dict(result) if result else {}
        except:
            return {}
    
    def get_all_members(self, guild_id: int = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Все участники (опционально по серверу)"""
        if not self.conn:
            return []
        try:
            if guild_id:
                cursor = self.conn.execute('''
                    SELECT user_id, xp, total_messages, voice_seconds
                    FROM members
                    WHERE guild_id = ?
                    ORDER BY xp DESC
                    LIMIT ?
                ''', (guild_id, limit))
            else:
                cursor = self.conn.execute('''
                    SELECT guild_id, user_id, xp, total_messages, voice_seconds
                    FROM members
                    ORDER BY xp DESC
                    LIMIT ?
                ''', (limit,))
            return [dict(row) for row in cursor.fetchall()]
        except:
            return []