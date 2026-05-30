"""非阻塞声音通知"""
import threading
import winsound

def play_sound(freq, dur):
    threading.Thread(target=lambda: winsound.Beep(freq, dur), daemon=True).start()