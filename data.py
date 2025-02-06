import sqlite3
from collections import defaultdict

def initialize_db():
    conn = sqlite3.connect('user_stats.db')
    c = conn.cursor()
    
    # Create the user_stats table if it doesn't exist
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_stats (
            user_id TEXT PRIMARY KEY,
            warnings INTEGER,
            streaks INTEGER,
            total_images INTEGER,
            completed_modules TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

def load_user_stats():
    conn = sqlite3.connect('user_stats.db')
    c = conn.cursor()
    c.execute('SELECT * FROM user_stats')
    rows = c.fetchall()
    stats = {
        'warnings': defaultdict(int),
        'streaks': defaultdict(int),
        'total_images': defaultdict(int),
        'completed_modules': defaultdict(set),
        'eliminations': set()
    }
    for row in rows:
        user_id, warnings, streaks, total_images, completed_modules = row
        stats['warnings'][user_id] = warnings
        stats['streaks'][user_id] = streaks
        stats['total_images'][user_id] = total_images
        if completed_modules:
            stats['completed_modules'][user_id] = set(completed_modules.split(','))
    conn.close()
    return stats

def save_user_stats(user_id):
    conn = sqlite3.connect('user_stats.db')
    c = conn.cursor()
    c.execute('''
        INSERT INTO user_stats (user_id, warnings, streaks, total_images, completed_modules)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            warnings=excluded.warnings,
            streaks=excluded.streaks,
            total_images=excluded.total_images,
            completed_modules=excluded.completed_modules
    ''', (user_id, user_stats['warnings'][user_id], user_stats['streaks'][user_id],
           user_stats['total_images'][user_id], ','.join(user_stats['completed_modules'][user_id])))
    conn.commit()
    conn.close()

# Initialize the database and create the table if it doesn't exist
initialize_db()

# Load user stats from the database
user_stats = load_user_stats()
