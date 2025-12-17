import os
import json
from pathlib import Path

def create_game_template(Developer_name, game_name, game_type, min_players, max_players):

    game_dir = Path("games")/ game_name / "1.0.0" 
    game_dir.mkdir(parents=True, exist_ok=True)
    
    config = {
        "name": game_name,
        "version": "1.0.0",
        "author": Developer_name,
        "game_type": game_type,
        "min_players": min_players,
        "max_players": max_players,
    }
    
    config_path = game_dir / "game_config.json"
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    server_template = '''
"""
遊戲伺服器範本
此檔案會被 main_server 透過 subprocess 呼叫執行
命令格式: python game_server.py 
"""

import socket
import sys
import random
import struct
import json
from typing import Optional

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

    
class GameServer:
    def __init__(self, port, max_players):
        self.host = '0.0.0.0'
        self.port = port
        self.max_players = max_players
        self.clients = []
        self.running = True
        
    def start(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((self.host, self.port))
        server_socket.listen(self.max_players)
        
        print(f"[Game Server] Listening on {self.host}:{self.port}")
        print(f"[Game Server] Waiting for {self.max_players} players...")
        
        try:
            while len(self.clients) < self.max_players and self.running:
                server_socket.settimeout(1.0)
                try:
                    client_socket, addr = server_socket.accept()
                    player_id = len(self.clients) + 1
                    self.clients.append((client_socket, addr, player_id))
                    print(f"[Game Server] Player {player_id} connected from {addr}")
                    
                    hello_msg = {
                        'type': 'HELLO',
                        'player_id': player_id
                    }

                    send_message(client_socket, hello_msg)
                    
                except socket.timeout:
                    continue
            
            # 所有玩家已連線，開始遊戲
            if len(self.clients) == self.max_players:
                print(f"[Game Server] All players connected. Starting game...")
                
                # ===== Implement your game logic here and rememer to broadcast the game starting message =====
                self.run_game()
                
        except KeyboardInterrupt:
            print("[Game Server] Shutting down...")
        finally:
            self.cleanup()
            server_socket.close()
    
    def run_game(self):
        raise NotImplementedError

    def broadcast(self, data):
        raise NotImplementedError
    
    def cleanup(self):
        print("[Game Server] Cleaning up...")
        for client_socket, _, _ in self.clients:
            try:
                client_socket.close()
            except:
                pass

def main():
    port = int(sys.argv[1])
    max_players = int(sys.argv[2])

    server = GameServer(port, max_players)
    server.start()

if __name__ == '__main__':
    main()

'''
    
    server_path = game_dir / "game_server.py"
    with open(server_path, 'w', encoding='utf-8') as f:
        f.write(server_template)
    
    # ==================== 3. 建立 game_client.py ====================
    client_template = '''
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
from typing import Optional

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
        
    def connect(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            return True
        except Exception as e:
            return False
    
    def start(self):
        raise NotImplementedError
        
        # 主執行緒等待
        try:
            recv_thread.join()
        finally:
            self.cleanup()
    
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
            
        elif msg_type == 'GAME_START':
            raise NotImplementedError
            
    def cleanup(self):
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        print("[Game Client] Disconnected")
        print()

def main():
    host = sys.argv[1]
    port = int(sys.argv[2])
    
    client = GameClient(host, port)
    client.start()

if __name__ == '__main__':
    main()

'''
    
    client_path = game_dir / "game_client.py"
    with open(client_path, 'w', encoding='utf-8') as f:
        f.write(client_template)
    
    # 設定執行權限 (Linux/Mac)
    try:
        os.chmod(server_path, 0o755)
        os.chmod(client_path, 0o755)
    except:
        pass
    
    print(f"✓ Game Template Created: {game_dir}")

def interactive_create(Developer_name):
    print("\n" + "=" * 60)
    print("Game Template Creation Tool")
    print("=" * 60 + "\n")

    # ---- Game Name ----
    while True:
        game_name = input("Please enter the game name (or type 'cancel' to exit): ").strip()
        if game_name.lower() == "cancel":
            return
        if game_name:
            break
        print("Error: Game name cannot be empty.\n")

    # ---- Game Type ----
    print("\nGame Type:")
    print("1. CLI (Command-Line Interface)")
    print("2. GUI (Graphical User Interface)")

    while True:
        choice = input("Choose (1-2) [default: 1] or type 'cancel': ").strip() or "1"
        if choice.lower() == "cancel":
            return
        if choice in ("1", "2"):
            game_type = "CLI" if choice == "1" else "GUI"
            break
        print("Invalid input. Please enter 1, 2, or 'cancel'.\n")

    # ---- Minimum Players ----
    while True:
        min_players = input("\nMinimum number of players [default: 2] or type 'cancel': ").strip() or "2"
        if min_players.lower() == "cancel":
            return
        try:
            min_players = int(min_players)
            if min_players >= 1:
                break
            print("Error: Minimum players must be at least 1.\n")
        except ValueError:
            print("Error: Please enter a valid number.\n")

    # ---- Maximum Players ----
    while True:
        max_players = input("Maximum number of players [default: 2] or type 'cancel': ").strip() or "2"
        if max_players.lower() == "cancel":
            return
        try:
            max_players = int(max_players)
            if max_players >= min_players:
                break
            print(f"Error: Maximum players must be > minimum players ({min_players}).\n")
        except ValueError:
            print("Error: Please enter a valid number.\n")

    # ---- Create Template ----
    print("\nCreating game template...\n")
    create_game_template(Developer_name, game_name, game_type, min_players, max_players)
    print("Game template created successfully!")

if __name__ == '__main__':
    interactive_create()