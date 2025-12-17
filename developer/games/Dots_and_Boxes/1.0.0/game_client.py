"""
遊戲客戶端範本
此檔案會被 player client 透過 subprocess 呼叫執行
命令格式: python game_client.py  
"""

import socket
import sys
import threading
import struct
import json
import os
from typing import Optional
import tkinter as tk
from tkinter import messagebox

CHUNK_SIZE = 65536

def send_message(sock: socket.socket, message):
    message_str = json.dumps(message)
    data = message_str.encode('utf-8')
    total_length = len(data)
    
    offset = 0
    while offset < total_length:
        remaining = total_length - offset
        chunk_length = min(CHUNK_SIZE, remaining)
        chunk_data = data[offset:offset + chunk_length]
        
        length_prefix = struct.pack('!I', chunk_length)
        sock.sendall(length_prefix)
        sock.sendall(chunk_data)
        
        offset += chunk_length
    
    end_marker = struct.pack('!I', 0)
    sock.sendall(end_marker)

def recv_message(sock: socket.socket) -> Optional[str]:
    chunks = []
    total_received = 0

    while True:
        length_data = recv_exact(sock, 4)
        if not length_data:
            return None
        
        chunk_length = struct.unpack('!I', length_data)[0]
        
        if chunk_length == 0:
            break
        
        if chunk_length > CHUNK_SIZE:
            raise ValueError(f"Invalid chunk length: {chunk_length}")
        
        total_received += chunk_length
        
        chunk_data = recv_exact(sock, chunk_length)
        if not chunk_data:
            return None
        
        chunks.append(chunk_data)

    complete_data = b''.join(chunks)
    return json.loads(complete_data.decode('utf-8'))

def recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    data = bytearray()
    while len(data) < n:
        packet = sock.recv(n - len(data))
        if not packet:
            return None
        data.extend(packet)
    return bytes(data)


class GameClient:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.socket = None
        self.player_id = None
        self.running = True
        self.waiting_for_input = False
        
        # Game state
        self.grid_size = 5
        # horizontal_lines[row][col] connects dot(row, col) to dot(row, col+1)
        self.horizontal_lines = [[False] * (self.grid_size - 1) for _ in range(self.grid_size)]
        # vertical_lines[row][col] connects dot(row, col) to dot(row+1, col)
        self.vertical_lines = [[False] * self.grid_size for _ in range(self.grid_size - 1)]
        self.boxes = [[0] * (self.grid_size - 1) for _ in range(self.grid_size - 1)]
        self.scores = {1: 0, 2: 0}
        self.current_player = 1
        self.my_turn = False
        
        # GUI
        self.root = None
        self.canvas = None
        self.status_label = None
        self.score_label = None
        self.dot_size = 8
        self.cell_size = 80
        self.margin = 50
        
    def connect(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            return True
        except Exception as e:
            return False
    
    def start(self):
        if not self.connect():
            print("[Game Client] Failed to connect to server")
            return
        
        # Start receive thread
        recv_thread = threading.Thread(target=self.receive_messages, daemon=True)
        recv_thread.start()
        
        # Start GUI
        self.root = tk.Tk()
        self.root.title("Dots and Boxes")
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # Status label
        self.status_label = tk.Label(self.root, text="Waiting for game to start...", font=("Arial", 14))
        self.status_label.pack(pady=10)
        
        # Score label
        self.score_label = tk.Label(self.root, text="Player 1: 0 | Player 2: 0", font=("Arial", 12))
        self.score_label.pack(pady=5)
        
        # Canvas
        canvas_width = self.cell_size * (self.grid_size - 1) + 2 * self.margin
        canvas_height = self.cell_size * (self.grid_size - 1) + 2 * self.margin
        self.canvas = tk.Canvas(self.root, width=canvas_width, height=canvas_height, bg='white')
        self.canvas.pack(padx=10, pady=10)
        self.canvas.bind("<Button-1>", self.on_canvas_click)
        
        # Draw initial empty board
        self.update_gui()
        
        self.root.mainloop()
        
        # 主執行緒等待
        try:
            recv_thread.join()
        finally:
            self.cleanup()
            os._exit(0)
    
    def receive_messages(self):
        while self.running:
            try:
                msg = recv_message(self.socket)
                if not msg:
                    self.running = False
                    break
                
                self.handle_message(msg)
                
            except Exception as e:
                self.running = False
                break
    
    def handle_message(self, data):
        msg_type = data.get('type')
        
        if msg_type == 'HELLO':
            self.player_id = data.get('player_id')
            print(f"[Game Client] Connected as Player {self.player_id}")
            
        elif msg_type == 'GAME_START':
            received_grid_size = data.get('grid_size', 5)
            if received_grid_size != self.grid_size:
                self.grid_size = received_grid_size
                self.horizontal_lines = [[False] * (self.grid_size - 1) for _ in range(self.grid_size)]
                self.vertical_lines = [[False] * self.grid_size for _ in range(self.grid_size - 1)]
                self.boxes = [[0] * (self.grid_size - 1) for _ in range(self.grid_size - 1)]
            self.current_player = data.get('current_player', 1)
            print("[Game Client] Game started!")
            self.root.after(0, self.update_gui)
            
        elif msg_type == 'YOUR_TURN':
            self.my_turn = True
            self.waiting_for_input = True
            self.root.after(0, self.update_status, "Your turn! Click between dots to draw a line.")
            self.root.after(0, self.update_gui)
            
        elif msg_type == 'GAME_STATE':
            self.horizontal_lines = data.get('horizontal_lines', [])
            self.vertical_lines = data.get('vertical_lines', [])
            self.boxes = data.get('boxes', [])
            self.scores = data.get('scores', {1: 0, 2: 0})
            self.current_player = data.get('current_player', 1)
            
            # Check if it's now my turn based on the game state
            if self.current_player == self.player_id and not self.waiting_for_input:
                self.my_turn = True
                self.waiting_for_input = True
                self.root.after(0, self.update_status, "Your turn! Click between dots to draw a line.")
            elif self.current_player != self.player_id:
                self.my_turn = False
                self.waiting_for_input = False
            
            self.root.after(0, self.update_gui)
            
        elif msg_type == 'INVALID_MOVE':
            self.root.after(0, lambda: messagebox.showwarning("Invalid Move", data.get('message', 'Invalid move')))
            
        elif msg_type == 'GAME_OVER':
            winner = data.get('winner', 0)
            scores = data.get('scores', {})
            
            if winner == 0:
                title = "Game Over - Draw!"
                msg = f"It's a draw!\n\nFinal Score:\nPlayer 1: {scores[1]}\nPlayer 2: {scores[2]}\n\nClose this window to return to the game lobby."
            elif winner == self.player_id:
                title = "Game Over - You Win!"
                msg = f"Congratulations! You win!\n\nFinal Score:\nPlayer 1: {scores[1]}\nPlayer 2: {scores[2]}\n\nClose this window to return to the game lobby."
            else:
                title = "Game Over - You Lose"
                msg = f"You lose!\n\nFinal Score:\nPlayer 1: {scores[1]}\nPlayer 2: {scores[2]}\n\nClose this window to return to the game lobby."
            
            self.my_turn = False
            self.waiting_for_input = False
            self.root.after(0, lambda: messagebox.showinfo(title, msg))
            self.root.after(100, self.update_status, "Game Over! Close window to return to lobby.")
    
    def update_gui(self):
        if not self.canvas:
            return
        
        self.canvas.delete("all")
        
        # Draw dots
        for row in range(self.grid_size):
            for col in range(self.grid_size):
                x = self.margin + col * self.cell_size
                y = self.margin + row * self.cell_size
                self.canvas.create_oval(
                    x - self.dot_size // 2, y - self.dot_size // 2,
                    x + self.dot_size // 2, y + self.dot_size // 2,
                    fill='black'
                )
        
        # Draw horizontal lines (row: 0 to grid_size-1, col: 0 to grid_size-2)
        if self.horizontal_lines and len(self.horizontal_lines) > 0:
            for row in range(len(self.horizontal_lines)):
                for col in range(len(self.horizontal_lines[0])):
                    if self.horizontal_lines[row][col]:
                        x1 = self.margin + col * self.cell_size
                        y1 = self.margin + row * self.cell_size
                        x2 = self.margin + (col + 1) * self.cell_size
                        y2 = y1
                        self.canvas.create_line(x1, y1, x2, y2, width=4, fill='blue')
        
        # Draw vertical lines (row: 0 to grid_size-2, col: 0 to grid_size-1)
        if self.vertical_lines and len(self.vertical_lines) > 0:
            for row in range(len(self.vertical_lines)):
                for col in range(len(self.vertical_lines[0])):
                    if self.vertical_lines[row][col]:
                        x1 = self.margin + col * self.cell_size
                        y1 = self.margin + row * self.cell_size
                        x2 = x1
                        y2 = self.margin + (row + 1) * self.cell_size
                        self.canvas.create_line(x1, y1, x2, y2, width=4, fill='blue')
        
        # Draw boxes
        if self.boxes and len(self.boxes) > 0:
            for row in range(len(self.boxes)):
                for col in range(len(self.boxes[0])):
                    if self.boxes[row][col] != 0:
                        x = self.margin + col * self.cell_size + self.cell_size // 2
                        y = self.margin + row * self.cell_size + self.cell_size // 2
                        color = '#FFB6C1' if self.boxes[row][col] == 1 else '#ADD8E6'
                        self.canvas.create_rectangle(
                            x - self.cell_size // 2 + 5, y - self.cell_size // 2 + 5,
                            x + self.cell_size // 2 - 5, y + self.cell_size // 2 - 5,
                            fill=color, outline=''
                        )
                        self.canvas.create_text(x, y, text=f"P{self.boxes[row][col]}", font=("Arial", 16, "bold"))
        
        # Update scores
        self.score_label.config(text=f"Player 1: {self.scores.get(1, 0)} | Player 2: {self.scores.get(2, 0)}")
        
        # Update status - check both my_turn and if current_player matches
        if self.my_turn and self.current_player == self.player_id:
            self.status_label.config(text="Your turn!", fg='green')
        elif self.current_player == self.player_id:
            self.status_label.config(text="Your turn!", fg='green')
        else:
            self.status_label.config(text=f"Player {self.current_player}'s turn", fg='black')
    
    def update_status(self, text):
        if self.status_label:
            self.status_label.config(text=text)
    
    def on_canvas_click(self, event):
        if not self.my_turn or not self.waiting_for_input:
            return
        
        if not self.horizontal_lines or not self.vertical_lines:
            return
        
        # Calculate which line was clicked
        x = event.x - self.margin
        y = event.y - self.margin
        
        # Check horizontal lines (row: 0 to grid_size-1, col: 0 to grid_size-2)
        for row in range(self.grid_size):
            for col in range(self.grid_size - 1):
                line_x1 = col * self.cell_size
                line_y = row * self.cell_size
                line_x2 = (col + 1) * self.cell_size
                
                if abs(y - line_y) < 15 and line_x1 - 15 < x < line_x2 + 15:
                    if not self.horizontal_lines[row][col]:
                        self.send_move('horizontal', row, col)
                        self.my_turn = False
                        self.waiting_for_input = False
                        return
        
        # Check vertical lines (row: 0 to grid_size-2, col: 0 to grid_size-1)
        for row in range(self.grid_size - 1):
            for col in range(self.grid_size):
                line_x = col * self.cell_size
                line_y1 = row * self.cell_size
                line_y2 = (row + 1) * self.cell_size
                
                if abs(x - line_x) < 15 and line_y1 - 15 < y < line_y2 + 15:
                    if not self.vertical_lines[row][col]:
                        self.send_move('vertical', row, col)
                        self.my_turn = False
                        self.waiting_for_input = False
                        return
    
    def send_move(self, line_type, row, col):
        move_msg = {
            'type': 'MOVE',
            'line_type': line_type,
            'row': row,
            'col': col
        }
        try:
            send_message(self.socket, move_msg)
        except Exception as e:
            print(f"[Game Client] Error sending move: {e}")
    
    def on_closing(self):
        self.running = False
        self.root.destroy()
        
    def cleanup(self):
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        print("[Game Client] Disconnected\n")

def main():
    host = sys.argv[1]
    port = int(sys.argv[2])
    
    client = GameClient(host, port)
    client.start()

if __name__ == '__main__':
    main()