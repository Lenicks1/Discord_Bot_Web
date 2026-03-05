from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from functools import wraps

api = Blueprint('api', __name__, url_prefix='/api/v1')

# Декоратор для проверки API ключа
def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key or api_key != os.getenv('API_SECRET_KEY'):
            return jsonify({'error': 'Invalid API key'}), 401
        return f(*args, **kwargs)
    return decorated

@api.route('/stats', methods=['GET'])
@require_api_key
def get_stats():
    """Получить общую статистику бота"""
    try:
        if bot_db.connect():
            stats = {
                'servers': bot_db.get_server_count(),
                'users': bot_db.get_user_count(),
                'messages': bot_db.get_message_count(),
                'quotes': bot_db.get_quote_count()
            }
            bot_db.close()
            return jsonify({'success': True, 'data': stats})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@api.route('/guilds', methods=['GET'])
@require_api_key
def get_guilds():
    """Получить список серверов"""
    try:
        if bot_db.connect():
            guilds = bot_db.get_all_guilds()
            bot_db.close()
            return jsonify({'success': True, 'data': guilds})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@api.route('/users/top', methods=['GET'])
@require_api_key
def get_top_users():
    """Получить топ пользователей"""
    limit = request.args.get('limit', 10, type=int)
    try:
        if bot_db.connect():
            users = bot_db.get_top_users(limit)
            bot_db.close()
            return jsonify({'success': True, 'data': users})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@api.route('/quotes', methods=['GET'])
@require_api_key
def get_quotes():
    """Получить цитаты"""
    limit = request.args.get('limit', 10, type=int)
    try:
        if bot_db.connect():
            quotes = bot_db.get_all_quotes(limit)
            bot_db.close()
            return jsonify({'success': True, 'data': quotes})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Регистрация blueprint в app.py
# app.register_blueprint(api)