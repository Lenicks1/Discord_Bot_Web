from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_sqlalchemy import SQLAlchemy
from config import Config
from models import db, User, BotDatabase
from dotenv import load_dotenv
import os
import requests
from urllib.parse import urlencode
import json
from datetime import datetime

load_dotenv()

app = Flask(__name__)
app.config.from_object(Config)

db.init_app(app)

# Настройка Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Discord OAuth2 настройки
DISCORD_CLIENT_ID = os.getenv('DISCORD_CLIENT_ID')
DISCORD_CLIENT_SECRET = os.getenv('DISCORD_CLIENT_SECRET')
DISCORD_REDIRECT_URI = os.getenv('DISCORD_REDIRECT_URI')
DISCORD_AUTH_URL = 'https://discord.com/api/oauth2/authorize'
DISCORD_TOKEN_URL = 'https://discord.com/api/oauth2/token'
DISCORD_USER_URL = 'https://discord.com/api/users/@me'
DISCORD_GUILDS_URL = 'https://discord.com/api/users/@me/guilds'

# Подключение к БД бота
bot_db = BotDatabase(app.config['BOT_DB_PATH'])

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- Маршруты ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            flash('Вход выполнен успешно!', 'success')
            
            if user.is_admin:
                return redirect(url_for('admin_dashboard'))
            return redirect(url_for('index'))
        
        flash('Неверный логин или пароль', 'error')
    
    return render_template('login.html')

@app.route('/auth/discord')
def discord_login():
    """Перенаправление на Discord для авторизации"""
    params = {
        'client_id': DISCORD_CLIENT_ID,
        'redirect_uri': DISCORD_REDIRECT_URI,
        'response_type': 'code',
        'scope': 'identify guilds'
    }
    auth_url = f"{DISCORD_AUTH_URL}?{urlencode(params)}"
    return redirect(auth_url)

@app.route('/auth/discord/callback')
def discord_callback():
    """Обработка callback от Discord"""
    code = request.args.get('code')
    
    if not code:
        flash('Ошибка авторизации: нет кода', 'error')
        return redirect(url_for('login'))
    
    # Получаем токен
    token_data = {
        'client_id': DISCORD_CLIENT_ID,
        'client_secret': DISCORD_CLIENT_SECRET,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': DISCORD_REDIRECT_URI
    }
    
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    r = requests.post(DISCORD_TOKEN_URL, data=token_data, headers=headers)
    
    if r.status_code != 200:
        flash('Ошибка получения токена Discord', 'error')
        return redirect(url_for('login'))
    
    access_token = r.json()['access_token']
    
    # Получаем информацию о пользователе
    headers = {'Authorization': f'Bearer {access_token}'}
    r = requests.get(DISCORD_USER_URL, headers=headers)
    
    if r.status_code != 200:
        flash('Ошибка получения данных пользователя', 'error')
        return redirect(url_for('login'))
    
    user_data = r.json()
    discord_id = user_data['id']
    username = user_data['username']
    avatar = user_data.get('avatar')
    
    # Формируем URL аватара
    if avatar:
        avatar_url = f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar}.png"
    else:
        default_avatar = int(discord_id) >> 22 % 6
        avatar_url = f"https://cdn.discordapp.com/embed/avatars/{default_avatar}.png"
    
    # Получаем сервера пользователя
    r = requests.get(DISCORD_GUILDS_URL, headers=headers)
    guilds = []
    if r.status_code == 200:
        guilds = r.json()
    
    # Создаём или находим пользователя
    user = User.query.filter_by(discord_id=discord_id).first()
    
    if not user:
        user = User.query.filter_by(username=username).first()
        if user:
            user.discord_id = discord_id
            user.discord_avatar = avatar_url
        else:
            user = User(
                username=username,
                discord_id=discord_id,
                discord_avatar=avatar_url,
                is_admin=(username == 'Lenicks')
            )
            user.set_password(os.urandom(24).hex())
        
        db.session.add(user)
        db.session.commit()
        flash('Аккаунт создан через Discord!', 'success')
    else:
        user.discord_avatar = avatar_url
        db.session.commit()
        flash('Вход через Discord выполнен!', 'success')
    
    login_user(user)
    
    if user.is_admin:
        return redirect(url_for('admin_dashboard'))
    return redirect(url_for('index'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы вышли из аккаунта', 'info')
    return redirect(url_for('index'))

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        flash('У вас нет прав доступа', 'error')
        return redirect(url_for('index'))
    
    stats = {'servers': 0, 'users': 0, 'messages': 0, 'quotes': 0}
    
    try:
        if bot_db.connect():
            stats = {
                'servers': bot_db.get_server_count(),
                'users': bot_db.get_user_count(),
                'messages': bot_db.get_message_count(),
                'quotes': bot_db.get_quote_count()
            }
            bot_db.close()
    except Exception as e:
        flash(f'Ошибка подключения к БД бота: {e}', 'error')
    
    return render_template('admin/dashboard.html', username=current_user.username, stats=stats)

@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
def admin_settings():
    """Настройки бота через сайт"""
    if not current_user.is_admin:
        flash('У вас нет прав доступа', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        action = request.form.get('action')
        guild_id = request.form.get('guild_id', type=int)
        
        if not guild_id:
            flash('Выберите сервер', 'error')
            return redirect(url_for('admin_settings'))
        
        try:
            if bot_db.connect():
                if action == 'set_log':
                    channel_id = request.form.get('log_channel_id', type=int)
                    bot_db.set_log_channel(guild_id, channel_id)
                    flash('Лог-канал установлен!', 'success')
                
                elif action == 'set_welcome':
                    channel_id = request.form.get('welcome_channel_id', type=int)
                    bot_db.set_welcome_channel(guild_id, channel_id)
                    flash('Канал приветствий установлен!', 'success')
                
                elif action == 'set_goodbye':
                    channel_id = request.form.get('goodbye_channel_id', type=int)
                    bot_db.set_goodbye_channel(guild_id, channel_id)
                    flash('Канал прощаний установлен!', 'success')
                
                elif action == 'set_autorole':
                    role_id = request.form.get('autorole_id', type=int)
                    bot_db.set_autorole(guild_id, role_id)
                    flash('Autorole установлен!', 'success')
                
                bot_db.close()
        except Exception as e:
            flash(f'Ошибка: {e}', 'error')
        
        return redirect(url_for('admin_settings'))
    
    # Получаем список серверов из БД
    guilds = []
    try:
        if bot_db.connect():
            guilds = bot_db.get_all_guilds()
            bot_db.close()
    except Exception as e:
        flash(f'Ошибка: {e}', 'error')
    
    return render_template('admin/settings.html', username=current_user.username, guilds=guilds)

@app.route('/admin/moderation')
@login_required
def admin_moderation():
    """Модерация через сайт"""
    if not current_user.is_admin:
        flash('У вас нет прав доступа', 'error')
        return redirect(url_for('index'))
    
    guilds = []
    try:
        if bot_db.connect():
            guilds = bot_db.get_all_guilds()
            bot_db.close()
    except Exception as e:
        flash(f'Ошибка: {e}', 'error')
    
    return render_template('admin/moderation.html', username=current_user.username, guilds=guilds)

@app.route('/admin/quotes')
@login_required
def admin_quotes():
    """Управление цитатами"""
    if not current_user.is_admin:
        flash('У вас нет прав доступа', 'error')
        return redirect(url_for('index'))
    
    quotes = []
    try:
        if bot_db.connect():
            quotes = bot_db.get_all_quotes(100)
            bot_db.close()
    except Exception as e:
        flash(f'Ошибка: {e}', 'error')
    
    return render_template('admin/quotes.html', username=current_user.username, quotes=quotes)

@app.route('/admin/quotes/delete/<int:quote_id>', methods=['POST'])
@login_required
def delete_quote(quote_id):
    """Удаление цитаты"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        if bot_db.connect():
            quotes = bot_db.get_all_quotes(100)
            quote = next((q for q in quotes if q['id'] == quote_id), None)
            
            if quote:
                success = bot_db.delete_quote(quote['guild_id'], quote_id, 0, True)
                bot_db.close()
                
                if success:
                    return jsonify({'success': True, 'message': 'Цитата удалена'})
            
            bot_db.close()
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': 'Цитата не найдена'}), 404

@app.route('/admin/stats')
@login_required
def admin_stats():
    """Страница со статистикой и графиками"""
    if not current_user.is_admin:
        flash('У вас нет прав доступа', 'error')
        return redirect(url_for('index'))
    
    stats = {'servers': 0, 'users': 0, 'messages': 0, 'quotes': 0}
    chart_data = {'messages_labels': [], 'messages_count': [], 'voice_labels': [], 'voice_hours': []}
    xp_distribution = {'labels': [], 'counts': []}
    top_users = {'names': [], 'xp': []}
    
    try:
        if bot_db.connect():
            stats = {
                'servers': bot_db.get_server_count(),
                'users': bot_db.get_user_count(),
                'messages': bot_db.get_message_count(),
                'quotes': bot_db.get_quote_count()
            }
            
            message_stats = bot_db.get_stats_by_date(7)
            chart_data['messages_labels'] = [row['date'] for row in message_stats]
            chart_data['messages_count'] = [row['total'] for row in message_stats]
            
            voice_stats = bot_db.get_voice_stats_by_date(7)
            chart_data['voice_labels'] = [row['date'] for row in voice_stats]
            chart_data['voice_hours'] = [round(row['total'] / 3600, 2) for row in voice_stats]
            
            xp_data = bot_db.get_xp_distribution()
            xp_distribution['labels'] = [row['range'] for row in xp_data]
            xp_distribution['counts'] = [row['count'] for row in xp_data]
            
            top_users_data = bot_db.get_top_users(10)
            top_users['names'] = [f"User #{row['user_id']}" for row in top_users_data]
            top_users['xp'] = [row['xp'] for row in top_users_data]
            
            bot_db.close()
    except Exception as e:
        flash(f'Ошибка: {e}', 'error')
    
    return render_template('admin/stats.html', 
                         username=current_user.username, 
                         stats=stats,
                         chart_data=chart_data,
                         xp_distribution=xp_distribution,
                         top_users=top_users)

@app.route('/admin/users')
@login_required
def admin_users():
    if not current_user.is_admin:
        flash('У вас нет прав доступа', 'error')
        return redirect(url_for('index'))
    
    users = []
    try:
        if bot_db.connect():
            users = bot_db.get_top_users(50)
            bot_db.close()
    except Exception as e:
        flash(f'Ошибка: {e}', 'error')
    
    return render_template('admin/users.html', users=users)

@app.route('/admin/guilds')
@login_required
def admin_guilds():
    if not current_user.is_admin:
        flash('У вас нет прав доступа', 'error')
        return redirect(url_for('index'))
    
    guilds = []
    try:
        if bot_db.connect():
            guilds = bot_db.get_all_guilds()
            bot_db.close()
    except Exception as e:
        flash(f'Ошибка: {e}', 'error')
    
    return render_template('admin/guilds.html', guilds=guilds)

@app.route('/api/stats')
@login_required
def api_stats():
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    stats = {'servers': 0, 'users': 0, 'messages': 0, 'quotes': 0}
    try:
        if bot_db.connect():
            stats = {
                'servers': bot_db.get_server_count(),
                'users': bot_db.get_user_count(),
                'messages': bot_db.get_message_count(),
                'quotes': bot_db.get_quote_count()
            }
            bot_db.close()
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/stats_data')
@login_required
def api_stats_data():
    """API для получения данных графиков"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403
    
    days = request.args.get('days', 7, type=int)
    
    try:
        if bot_db.connect():
            message_stats = bot_db.get_stats_by_date(days)
            voice_stats = bot_db.get_voice_stats_by_date(days)
            
            data = {
                'messages_labels': [row['date'] for row in message_stats],
                'messages_count': [row['total'] for row in message_stats],
                'voice_labels': [row['date'] for row in voice_stats],
                'voice_hours': [round(row['total'] / 3600, 2) for row in voice_stats]
            }
            bot_db.close()
            return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
    return jsonify({'error': 'No data'}), 404

@app.route('/profile')
@login_required
def profile():
    """Личный кабинет пользователя"""
    return render_template('profile.html', user=current_user)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        # Создаём админа если нет
        admin = User.query.filter_by(username='Lenicks').first()
        if not admin:
            admin = User(username='Lenicks', is_admin=True)
            admin.set_password('Ladminlendan')
            db.session.add(admin)
            db.session.commit()
            print('✅ Админ создан!')
    
    app.run(debug=True, port=5000)