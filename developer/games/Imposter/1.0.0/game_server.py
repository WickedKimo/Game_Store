import socket
import sys
import random
import struct
import json
import time
import select
from typing import Optional, List, Dict, Tuple

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
    while True:
        length_data = recv_exact(sock, 4)
        if not length_data:
            return None
        
        chunk_length = struct.unpack('!I', length_data)[0]
        
        if chunk_length == 0:
            break
        
        if chunk_length > CHUNK_SIZE:
            raise ValueError(f"Invalid chunk length: {chunk_length}")
        
        chunk_data = recv_exact(sock, chunk_length)
        if not chunk_data:
            return None
        
        chunks.append(chunk_data)

    complete_data = b''.join(chunks)
    try:
        return json.loads(complete_data.decode('utf-8'))
    except:
        return None

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
        self.clients: List[Tuple[socket.socket, tuple, int]] = []
        self.socket_to_player: Dict[socket.socket, int] = {}
        self.running = True
        
        # Game state
        self.secret_word = ""
        self.imposter_word = ""
        self.roles: Dict[int, str] = {}
        self.alive_players: List[int] = []
        self.current_speaker_index = -1
        self.descriptions: Dict[int, str] = {}
        self.game_phase = "waiting"
        self.votes: Dict[int, int] = {}

        self.word_pairs = [
            ("蘋果", "香蕉"), ("貓", "狗"), ("咖啡", "茶"), ("手機", "電腦"),
            ("足球", "籃球"), ("夏天", "冬天"), ("電影", "音樂"), ("書", "漫畫"),
            ("火車", "飛機"), ("巧克力", "冰淇淋"), ("披薩", "漢堡"), ("海灘", "雪山"),
            ("自行車", "汽車"), ("鋼琴", "吉他"), ("玫瑰", "鬱金香"),
        ]

    def start(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((self.host, self.port))
        server_socket.listen(self.max_players)
        server_socket.setblocking(False)

        print(f"[Game Server] Listening on {self.host}:{self.port}")
        print(f"[Game Server] Waiting for {self.max_players} players...")

        inputs = [server_socket]

        try:
            while len(self.clients) < self.max_players and self.running:
                readable, _, _ = select.select(inputs, [], [], 1.0)
                if server_socket in readable:
                    client_socket, addr = server_socket.accept()
                    client_socket.setblocking(False)
                    player_id = len(self.clients) + 1
                    self.clients.append((client_socket, addr, player_id))
                    self.socket_to_player[client_socket] = player_id
                    inputs.append(client_socket)
                    print(f"[Game Server] Player {player_id} connected from {addr}")
                    
                    send_message(client_socket, {
                        'type': 'HELLO',
                        'player_id': player_id
                    })

            if len(self.clients) == self.max_players:
                print(f"[Game Server] All players connected. Starting game...")
                inputs.remove(server_socket)
                self.setup_game()
                self.run_game(inputs)
                
        except KeyboardInterrupt:
            print("[Game Server] Shutting down...")
        finally:
            self.cleanup()
            server_socket.close()

    def setup_game(self):
        self.secret_word, self.imposter_word = random.choice(self.word_pairs)
        imposter_id = random.choice(range(1, self.max_players + 1))
        
        self.alive_players = list(range(1, self.max_players + 1))
        
        for client_sock, _, player_id in self.clients:
            role = "imposter" if player_id == imposter_id else "civilian"
            self.roles[player_id] = role
            word_to_send = self.imposter_word if role == "imposter" else self.secret_word
            
            send_message(client_sock, {
                'type': 'GAME_START',
                'your_role': role,
                'your_word': word_to_send,
            })
        
        time.sleep(2)
        
        self.game_phase = "describing"
        self.current_speaker_index = -1
        self.descriptions.clear()
        
        self.broadcast({
            'type': 'ROUND_START',
            'phase': 'describing',
            'message': '遊戲開始！請輪流描述你的單字（不能直接說出單字）'
        })
        
        self.next_speaker()

    def next_speaker(self):
        if not self.alive_players:
            return
        
        self.current_speaker_index = (self.current_speaker_index + 1) % len(self.alive_players)
        current_player = self.alive_players[self.current_speaker_index]
        
        self.broadcast({
            'type': 'YOUR_TURN',
            'speaker_id': current_player,
            'message': f'輪到玩家 {current_player} 描述！請輸入你的描述：'
        })

    def run_game(self, inputs: List[socket.socket]):
        while self.running and self.game_phase != "ended":
            readable, _, exceptional = select.select(inputs, [], inputs, 1.0)
            
            for sock in readable:
                msg = recv_message(sock)
                if msg is None:  # 真正斷線
                    self.remove_player_by_socket(sock)
                    if sock in inputs:
                        inputs.remove(sock)
                    continue
                
                player_id = self.socket_to_player.get(sock)
                if player_id is None:
                    continue
                
                # 被淘汰的玩家發來的訊息一律忽略（防止作弊）
                if player_id not in self.alive_players:
                    continue
                
                self.handle_client_message(player_id, msg)
            
            for sock in exceptional:
                self.remove_player_by_socket(sock)
                if sock in inputs:
                    inputs.remove(sock)
        
        if self.game_phase == "ended":
            time.sleep(8)  # 讓所有人看清楚結果

    def handle_client_message(self, player_id: int, msg: dict):
        msg_type = msg.get('type')
        
        if msg_type == 'DESCRIPTION' and self.game_phase == "describing":
            description = msg.get('text', '').strip()
            if not description:
                self.send_to_player(player_id, {'type': 'ERROR', 'message': '描述不能為空！'})
                return
            
            self.descriptions[player_id] = description
            
            self.broadcast({
                'type': 'PLAYER_DESCRIBED',
                'player_id': player_id,
                'description': description
            })
            
            if set(self.descriptions.keys()) >= set(self.alive_players):
                self.start_voting()
            else:
                self.next_speaker()
        
        elif msg_type == 'VOTE' and self.game_phase == "voting":
            target_id = msg.get('target_id')
            if target_id not in self.alive_players or target_id == player_id:
                self.send_to_player(player_id, {'type': 'ERROR', 'message': '無效的投票目標'})
                return
            
            self.votes[player_id] = target_id
            self.send_to_player(player_id, {'type': 'VOTE_CONFIRMED', 'target': target_id})
            
            if len(self.votes) == len(self.alive_players):
                self.resolve_voting()

    def start_voting(self):
        self.game_phase = "voting"
        self.votes.clear()
        
        self.broadcast({
            'type': 'VOTING_START',
            'alive_players': self.alive_players[:],
            'message': '所有玩家已描述完畢！現在開始投票，請輸入你要淘汰的玩家編號（不能投自己）：'
        })

    def resolve_voting(self):
        vote_count: Dict[int, int] = {}
        for target in self.votes.values():
            vote_count[target] = vote_count.get(target, 0) + 1
        
        max_votes = max(vote_count.values())
        candidates = [p for p, c in vote_count.items() if c == max_votes]
        eliminated = random.choice(candidates) if len(candidates) > 1 else candidates[0]
        
        # 僅從 alive_players 移除，不關閉連線
        if eliminated in self.alive_players:
            self.alive_players.remove(eliminated)
        
        self.broadcast({
            'type': 'PLAYER_ELIMINATED',
            'eliminated_id': eliminated,
            'message': f'玩家 {eliminated} 被淘汰！（該玩家可繼續觀戰）'
        })
        
        time.sleep(4)
        
        alive_imposters = sum(1 for p in self.alive_players if self.roles.get(p) == "imposter")
        alive_civilians = len(self.alive_players) - alive_imposters
        
        if alive_imposters == 0:
            self.end_game("civilians")
        elif alive_imposters >= alive_civilians:
            self.end_game("imposter")
        else:
            self.game_phase = "describing"
            self.current_speaker_index = -1
            self.descriptions.clear()
            self.broadcast({
                'type': 'ROUND_START',
                'phase': 'describing',
                'message': '新一輪開始！請繼續描述...'
            })
            self.next_speaker()

    def remove_player_by_socket(self, sock: socket.socket):
        player_id = self.socket_to_player.get(sock)
        if player_id:
            print(f"[Game Server] Player {player_id} disconnected unexpectedly")
            if player_id in self.alive_players:
                self.alive_players.remove(player_id)
            del self.socket_to_player[sock]
            self.clients = [c for c in self.clients if c[0] != sock]

    def end_game(self, winner: str):
        self.game_phase = "ended"
        reveal_roles = {pid: self.roles[pid] for pid in range(1, self.max_players + 1) if pid in self.roles}
        winner_msg = "平民獲勝！臥底已被找出！" if winner == "civilians" else "臥底獲勝！好人已無力回天！"
        
        self.broadcast({
            'type': 'GAME_OVER',
            'winner': winner,
            'message': f'遊戲結束！{winner_msg}\n單字是：{self.secret_word}（臥底單字：{self.imposter_word}）',
            'roles': reveal_roles,
            'secret_word': self.secret_word,
            'imposter_word': self.imposter_word
        })

    def broadcast(self, data: dict):
        # 廣播給所有仍連線的玩家（包括已被淘汰的）
        for client_sock, _, _ in self.clients[:]:
            try:
                send_message(client_sock, data)
            except:
                pass

    def send_to_player(self, player_id: int, data: dict):
        for client_sock, _, pid in self.clients:
            if pid == player_id:
                try:
                    send_message(client_sock, data)
                except:
                    pass
                break

    def cleanup(self):
        print("[Game Server] Cleaning up...")
        for client_sock, _, _ in self.clients:
            try:
                client_sock.close()
            except:
                pass
        self.clients.clear()
        self.socket_to_player.clear()

def main():
    if len(sys.argv) != 3:
        print("Usage: python game_server.py <port> <max_players>")
        sys.exit(1)
    
    port = int(sys.argv[1])
    max_players = int(sys.argv[2])

    server = GameServer(port, max_players)
    server.start()

if __name__ == '__main__':
    main()