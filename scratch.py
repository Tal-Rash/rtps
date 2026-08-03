import sqlite3

def main():
    conn = sqlite3.connect(r'g:\Мой диск\Codex\rtps\web_tabel\data\tabel.db')
    cur = conn.cursor()
    cur.execute("SELECT name, v, COUNT(*) FROM timesheet JOIN employees USING (tab_num, y) WHERE v IN ('О', 'ОВ') GROUP BY name, v")
    data = cur.fetchall()
    
    with open('out2.txt', 'w', encoding='utf-8') as f:
        for row in data:
            f.write(f"Name {row[0]}, Code {row[1]}: {row[2]}\n")
            
if __name__ == '__main__':
    main()
