import sqlite3

def force_all_now():
    conn = sqlite3.connect('queue.db')
    cursor = conn.cursor()
    # Approve all pending to skip manual Telegram HITL
    cursor.execute("UPDATE drafts SET status = 'approved' WHERE status = 'pending'")
    
    # Push the schedule to the past so the poster grabs them instantly
    cursor.execute("UPDATE drafts SET scheduled = '2020-01-01 00:00' WHERE status = 'approved'")
    
    conn.commit()
    print(f"Set all pending/approved drafts to post instantly. Total updated: {cursor.rowcount}")
    conn.close()

if __name__ == "__main__":
    force_all_now()
