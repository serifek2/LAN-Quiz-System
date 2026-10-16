import socket
import qrcode
import threading
import io
import time
import requests
import html
import random
from flask import Flask, render_template, request
from flask_socketio import SocketIO, emit
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
import os

# --- AYARLAR ---
print("--- QUICKQUIZ BAŞLATILIYOR ---")

if not os.path.exists('static'):
    os.makedirs('static')

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret_key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

# Global Değişkenler
players = {}
gui_queue = []
game_active = False
current_question_index = 0
SORULAR = []

# Yedek Sorular
TEMEL_SORULAR = [
    {"soru": "Which protocol is used for web pages?", "siklar": ["FTP", "SMTP", "HTTP", "DNS"], "dogru": 2},
    {"soru": "What does LAN stand for?", "siklar": ["Local Area Network", "Long Area Network", "Live Area Node", "Land Area Net"], "dogru": 0},
    {"soru": "Which device connects networks?", "siklar": ["Switch", "Router", "Hub", "Cable"], "dogru": 1}
]

hostname = socket.gethostname()
try:
    LOCAL_IP = socket.gethostbyname(hostname)
except:
    LOCAL_IP = "127.0.0.1"

PORT = 5555
URL = f"http://{LOCAL_IP}:{PORT}"
print(f"🔗 OYUN URL'Sİ: {URL}")

# --- SORU ÇEKME  ---
def fetch_network_questions(amount=3): 
    print("⏳ Sorular internetten çekiliyor...")
    url = f"https://opentdb.com/api.php?amount={amount}&category=18&type=multiple"
    try:
        response = requests.get(url, timeout=5)
        data = response.json()
        yeni_sorular = []
        if data['response_code'] == 0:
            for item in data['results']:
                soru_text = html.unescape(item['question'])
                dogru_cevap = html.unescape(item['correct_answer'])
                yanlis_cevaplar = [html.unescape(x) for x in item['incorrect_answers']]
                siklar = yanlis_cevaplar + [dogru_cevap]
                random.shuffle(siklar)
                dogru_index = siklar.index(dogru_cevap)
                yeni_sorular.append({"soru": soru_text, "siklar": siklar, "dogru": dogru_index})
        print(f"✅ {len(yeni_sorular)} soru alındı.")
        return yeni_sorular
    except:
        return []

# Soru Havuzu
internet_sorulari = fetch_network_questions(3)
if len(internet_sorulari) > 0:
    SORULAR = internet_sorulari
else:
    SORULAR = TEMEL_SORULAR[:3] 
    random.shuffle(SORULAR)

# --- FLASK ---
@app.route('/')
def index(): return render_template('index.html')

@socketio.on('join_game')
def handle_join(data):
    name = data['nickname']
    players[request.sid] = {"name": name, "score": 0}
    gui_queue.append(f"join:{name}")
    print(f"Katıldı: {name}")

@socketio.on('send_answer')
def handle_answer(data):
    if not game_active: return
    ans_idx = int(data['answer'])
    player = players.get(request.sid)
    if player:
        q_idx = current_question_index
        correct_idx = SORULAR[q_idx]['dogru']
        if ans_idx == correct_idx:
            player['score'] += 10
        emit('feedback', {'correct': (ans_idx == correct_idx)})

# --- PYTHON GUI ---
class TeacherApp:
    def __init__(self, root):
        self.root = root
        self.root.title("QuickQuiz Host")
        self.root.state('zoomed')
        self.root.configure(bg="#2c3e50")

        # 1. LOBBY FRAME
        self.frame_lobby = tk.Frame(root, bg="#2c3e50")
        self.frame_lobby.pack(fill="both", expand=True)

        tk.Label(self.frame_lobby, text="QuickQuiz LOBBY", font=("Segoe UI", 40, "bold"), bg="#2c3e50", fg="white").pack(pady=20)
        
        self.qr_label = tk.Label(self.frame_lobby, bg="white", padx=10, pady=10)
        self.qr_label.pack(pady=10)
        self.generate_qr()

        tk.Label(self.frame_lobby, text=f"Join at: {URL}", font=("Consolas", 24, "bold"), bg="#2c3e50", fg="#f1c40f").pack(pady=10)
        
        self.player_frame = tk.Frame(self.frame_lobby, bg="#2c3e50")
        self.player_frame.pack(pady=20, fill="x")
        self.player_labels = []

        self.btn_start = tk.Button(self.frame_lobby, text="START GAME ▶", font=("Segoe UI", 24, "bold"), bg="#27ae60", fg="white",
                                   activebackground="#2ecc71", command=self.start_game)
        self.btn_start.pack(pady=40, ipadx=20, ipady=10)

        # 2. GAME FRAME
        self.frame_game = tk.Frame(root, bg="#2c3e50")
        self.lbl_question = tk.Label(self.frame_game, text="", font=("Segoe UI", 32, "bold"), bg="#2c3e50", fg="white", wraplength=1000)
        self.lbl_question.pack(pady=50)

        self.frame_opts = tk.Frame(self.frame_game, bg="#2c3e50")
        self.frame_opts.pack(fill="both", expand=True, padx=50, pady=20)
        
        self.opt_labels = []
        self.colors = ["#e74c3c", "#3498db", "#f1c40f", "#2ecc71"]
        self.shapes = ["▲", "◆", "●", "■"]
        
        for i in range(4):
            lbl = tk.Label(self.frame_opts, text="", font=("Segoe UI", 24, "bold"), bg=self.colors[i], fg="white", relief="raised")
            lbl.grid(row=i//2, column=i%2, padx=20, pady=20, sticky="nsew")
            self.opt_labels.append(lbl)
            
        self.frame_opts.grid_columnconfigure(0, weight=1)
        self.frame_opts.grid_columnconfigure(1, weight=1)
        self.frame_opts.grid_rowconfigure(0, weight=1)
        self.frame_opts.grid_rowconfigure(1, weight=1)

        # 3. PODIUM FRAME
        self.frame_podium = tk.Frame(root, bg="#2c3e50")
        
        # 4. LEADERBOARD LIST FRAME
        self.frame_list = tk.Frame(root, bg="#2c3e50")

        self.root.after(100, self.check_queue)

    def generate_qr(self):
        qr = qrcode.QRCode(box_size=8, border=2)
        qr.add_data(URL)
        qr.make(fit=True)
        img = qr.make_image(fill='black', back_color='white')
        self.tk_image = ImageTk.PhotoImage(img)
        self.qr_label.config(image=self.tk_image)

    def check_queue(self):
        while gui_queue:
            msg = gui_queue.pop(0)
            if msg.startswith("join:"):
                name = msg.split(":")[1]
                lbl = tk.Label(self.player_frame, text=name, bg="#3498db", fg="white", font=("Segoe UI", 14, "bold"), padx=10, pady=5)
                lbl.pack(side="left", padx=5)
                self.player_labels.append(lbl)
        self.root.after(100, self.check_queue)

    def start_game(self):
        self.frame_lobby.pack_forget()
        self.frame_game.pack(fill="both", expand=True)
        threading.Thread(target=self.game_loop, daemon=True).start()

    def game_loop(self):
        global game_active, current_question_index
        for i, soru in enumerate(SORULAR):
            current_question_index = i
            game_active = True
            
            self.root.after(0, lambda s=soru: self.update_question_ui(s))
            socketio.emit('new_question')
            time.sleep(15)
            
            game_active = False
            socketio.emit('time_up')
            correct_idx = soru['dogru']
            self.root.after(0, lambda idx=correct_idx: self.highlight_correct_answer(idx))
            time.sleep(4)
        
        self.calculate_results()

    def update_question_ui(self, soru):
        self.lbl_question.config(text=soru['soru'])
        for idx, lbl in enumerate(self.opt_labels):
            lbl.config(text=f"{self.shapes[idx]} {soru['siklar'][idx]}", bg=self.colors[idx], fg="white")

    def highlight_correct_answer(self, correct_idx):
        for idx, lbl in enumerate(self.opt_labels):
            if idx == correct_idx: lbl.config(bg="#27ae60")
            else: lbl.config(bg="#95a5a6")

    def calculate_results(self):
       
        all_players = [{'name': p['name'], 'score': p['score']} for p in players.values()]
        
        # 2. Puana göre sırala
        all_players.sort(key=lambda x: x['score'], reverse=True)
        
        # 3. Telefonlara sonuçları gönder
        socketio.emit('game_over', {'players': all_players})
        
        # 4. Sonuçları kaydet ve Podyumu Göster
        self.final_results = all_players
        self.root.after(0, lambda: self.show_podium_ui(all_players))

    def show_podium_ui(self, results):
        self.frame_game.pack_forget()
        self.frame_podium.pack(fill="both", expand=True)
        
        # Temizle (tekrar çalışırsa üst üste binmesin)
        for widget in self.frame_podium.winfo_children():
            widget.destroy()

        tk.Label(self.frame_podium, text="🏆 WINNERS 🏆", font=("Segoe UI", 50, "bold"), bg="#2c3e50", fg="#f1c40f").pack(pady=30)
        
        podium_container = tk.Frame(self.frame_podium, bg="#2c3e50")
        podium_container.pack(expand=True, fill="both", padx=50)

        top3 = results[:3]

        def draw_bar(container, player, rank, color, height):
            frame = tk.Frame(container, bg="#2c3e50")
            frame.pack(side="left", expand=True, fill="y", padx=10)
            tk.Frame(frame, bg="#2c3e50", height=(400-height)).pack() # Boşluk
            tk.Label(frame, text=player['name'], font=("Segoe UI", 18, "bold"), bg="#2c3e50", fg="white").pack(pady=5)
            bar = tk.Frame(frame, bg=color, height=height, width=150)
            bar.pack()
            tk.Label(bar, text=f"#{rank}", font=("Segoe UI", 30, "bold"), bg=color, fg="white").place(relx=0.5, rely=0.5, anchor="center")
            tk.Label(frame, text=f"{player['score']} pts", font=("Segoe UI", 14), bg="#2c3e50", fg="#bdc3c7").pack(pady=5)

        if len(top3) > 1: draw_bar(podium_container, top3[1], 2, "#bdc3c7", 250)
        if len(top3) > 0: draw_bar(podium_container, top3[0], 1, "#f1c40f", 350)
        if len(top3) > 2: draw_bar(podium_container, top3[2], 3, "#e67e22", 150)

        # --- 5 SANİYE SONRA LİSTEYE GEÇ ---
        self.root.after(5000, self.show_full_leaderboard)

    def show_full_leaderboard(self):
        self.frame_podium.pack_forget() # Podyumu gizle
        self.frame_list.pack(fill="both", expand=True) # Listeyi aç
        
        tk.Label(self.frame_list, text="📋 FULL RANKING 📋", font=("Segoe UI", 40, "bold"), bg="#2c3e50", fg="white").pack(pady=30)
        
        scroll_frame = tk.Frame(self.frame_list, bg="#2c3e50")
        scroll_frame.pack(fill="both", expand=True, padx=100)

        # Başlıklar
        header = tk.Frame(scroll_frame, bg="#34495e", height=50)
        header.pack(fill="x", pady=5)
        tk.Label(header, text="RANK", font=("Segoe UI", 14, "bold"), bg="#34495e", fg="white", width=10).pack(side="left")
        tk.Label(header, text="PLAYER", font=("Segoe UI", 14, "bold"), bg="#34495e", fg="white", width=30).pack(side="left")
        tk.Label(header, text="SCORE", font=("Segoe UI", 14, "bold"), bg="#34495e", fg="white", width=10).pack(side="right")

        # Listeyi Dök
        for idx, p in enumerate(self.final_results, 1):
            bg_color = "#ecf0f1"
            if idx == 1: bg_color = "#f1c40f"
            elif idx == 2: bg_color = "#bdc3c7"
            elif idx == 3: bg_color = "#e67e22"
            
            row = tk.Frame(scroll_frame, bg=bg_color)
            row.pack(fill="x", pady=2)
            tk.Label(row, text=f"#{idx}", font=("Segoe UI", 14, "bold"), bg=bg_color, fg="#2c3e50", width=10).pack(side="left", pady=10)
            tk.Label(row, text=p['name'], font=("Segoe UI", 14, "bold"), bg=bg_color, fg="#2c3e50", width=30).pack(side="left")
            tk.Label(row, text=str(p['score']), font=("Segoe UI", 14, "bold"), bg=bg_color, fg="#2c3e50", width=10).pack(side="right")

def run_flask():
    socketio.run(app, host='0.0.0.0', port=PORT, allow_unsafe_werkzeug=True)

if __name__ == "__main__":
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    time.sleep(1)
    root = tk.Tk()
    app = TeacherApp(root)
    root.mainloop()