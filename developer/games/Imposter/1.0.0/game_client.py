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

def recv_message(sock: socket.socket) -> Optional[dict]:
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
        self.waiting_for_description = False
        self.waiting_for_vote = False
        
        self.my_role = None
        self.my_word = None
        self.alive_players = []
        
    def connect(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            return True
        except Exception as e:
            print(f"[Client] Connection failed: {e}")
            return False
    
    def start(self):
        if not self.connect():
            print("無法連線到伺服器")
            return
        
        print("已連線到遊戲伺服器，等待其他玩家...")
        
        recv_thread = threading.Thread(target=self.receive_messages, daemon=True)
        recv_thread.start()
        
        # 主執行緒處理輸入
        try:
            while self.running:
                if self.waiting_for_input:
                    user_input = input().strip()
                    if user_input:
                        self.handle_input(user_input)
                    self.waiting_for_input = False
                    self.waiting_for_description = False
                    self.waiting_for_vote = False
                else:
                    time.sleep(0.1)
        except (EOFError, KeyboardInterrupt):
            pass
        finally:
            self.cleanup()
    
    def receive_messages(self):
        while self.running:
            try:
                msg = recv_message(self.socket)
                if not msg:
                    print("\n[Client] 與伺服器斷線")
                    self.running = False
                    break
                
                self.handle_message(msg)
                
            except Exception as e:
                print(f"\n[Client] 接收錯誤: {e}")
                self.running = False
                break
    
    def handle_message(self, data):
        msg_type = data.get('type')
        
        if msg_type == 'HELLO':
            self.player_id = data.get('player_id')
            print(f"你被分配為玩家 {self.player_id}")
            
        elif msg_type == 'GAME_START':
            self.my_role = data['your_role']
            self.my_word = data['your_word']
            role_name = "臥底" if self.my_role == "imposter" else "平民"
            print("\n" + "="*50)
            print(f"  遊戲開始！")
            print(f"  你的單字是：『{self.my_word}』")
            print("="*50)
            
        elif msg_type == 'ROUND_START':
            print(f"\n{data['message']}")
            
        elif msg_type == 'YOUR_TURN':
            speaker = data['speaker_id']
            if speaker == self.player_id:
                print(f"\n>>> 輪到你描述了！請輸入你的描述（不能直接說單字）：")
                self.waiting_for_input = True
                self.waiting_for_description =True
            else:
                print(f"\n正在等待玩家 {speaker} 描述...")
        
        elif msg_type == 'PLAYER_DESCRIBED':
            pid = data['player_id']
            desc = data['description']
            print(f"玩家 {pid} 說：{desc}")
            
        elif msg_type == 'VOTING_START':
            self.alive_players = data['alive_players']
            print(f"\n{data['message']}")
            print(f"存活玩家：{self.alive_players}")
            print("請輸入你要投票淘汰的玩家編號：")
            self.waiting_for_input = True
            self.waiting_for_vote = True
            
        elif msg_type == 'VOTE_CONFIRMED':
            print(f"你投給了玩家 {data['target']}")
            
        elif msg_type == 'PLAYER_ELIMINATED':
            print(f"\n{data['message']}")
            
        elif msg_type == 'GAME_OVER':
            print("\n" + "="*60)
            print(f" {data['message']}")
            print(f" 真正單字：{data['secret_word']} （臥底單字：{data['imposter_word']}）")
            print(" 角色分配：")
            for pid, role in data['roles'].items():
                role_str = "臥底" if role == "imposter" else "平民"
                marker = " ← 你" if pid == self.player_id else ""
                print(f"    玩家 {pid}：{role_str}{marker}")
            print("="*60)
            self.running = False
            
        elif msg_type == 'ERROR':
            print(f"[錯誤] {data['message']}")
            self.waiting_for_input = True  # Allow retry
            
        else:
            print(f"[訊息] {data.get('message', str(data))}")
    
    def handle_input(self, text: str):
        if self.waiting_for_input:
            # Detect current expected input
            if self.waiting_for_description:  # crude detection
                # Assume description phase if we are waiting and no voting list
                send_message(self.socket, {
                    'type': 'DESCRIPTION',
                    'text': text
                })
            elif self.waiting_for_vote:
                # Voting phase
                try:
                    target = int(text)
                    while True:
                        if target in self.alive_players and target != self.player_id:
                            send_message(self.socket, {
                                'type': 'VOTE',
                                'target_id': target
                            })
                            break
                        else:
                            target = int(input("無效的玩家編號，請重新輸入："))
                except ValueError:
                    print("請輸入數字！")
                    self.waiting_for_input = True
    
    def cleanup(self):
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        print("[Game Client] Disconnected")

def main():
    if len(sys.argv) != 3:
        print("Usage: python game_client.py <host> <port>")
        return
    host = sys.argv[1]
    port = int(sys.argv[2])
    
    client = GameClient(host, port)
    client.start()

if __name__ == '__main__':
    import time
    main()