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
        self.game = Duel_25()
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
        self.game.deal_initial_cards()
        
        send_message(self.clients[0][0], {
            'type': 'GAME_START',
            'your_hand': self.game.player1_hand,
            'your_hp': self.game.player1_health,
            'opponent_hp': self.game.player2_health,
            'deck_size': len(self.game.deck)
        })
        
        send_message(self.clients[1][0], {
            'type': 'GAME_START',
            'your_hand': self.game.player2_hand,
            'your_hp': self.game.player2_health,
            'opponent_hp': self.game.player1_health,
            'deck_size': len(self.game.deck)
        })
        
        while self.running:
            self.game.round_num += 1
            print(f"\n[Duel 25 Server] === ROUND {self.game.round_num} ===")
            
            # 通知雙方回合開始
            self.broadcast({
                'type': 'ROUND_START',
                'round': self.game.round_num,
                'p1_hp': self.game.player1_health,
                'p2_hp': self.game.player2_health,
                'deck_size': len(self.game.deck)
            })
            
            # 收集玩家出牌
            p1_card = self.receive_card_choice(self.clients[0][0])
            p2_card = self.receive_card_choice(self.clients[1][0])
            
            if not p1_card or not p2_card:
                print("[Duel 25 Server] Player disconnected")
                break
            
            # 從手牌中移除
            self.game.player1_hand = [c for c in self.game.player1_hand if c != p1_card]
            self.game.player2_hand = [c for c in self.game.player2_hand if c != p2_card]
            
            print(f"[Duel 25 Server] P1 played: {p1_card['suit']}-{p1_card['value']}")
            print(f"[Duel 25 Server] P2 played: {p2_card['suit']}-{p2_card['value']}")
            
            # 計算結果
            new_p1_hp, new_p2_hp, p1_msg, p2_msg = self.game.compute_round_effects(
                p1_card, p2_card,
                self.game.player1_health,
                self.game.player2_health
            )
            
            self.game.player1_health = new_p1_hp
            self.game.player2_health = new_p2_hp
            
            # 發送回合結果
            send_message(self.clients[0][0], {
                'type': 'ROUND_RESULT',
                'your_card': p1_card,
                'opponent_card': p2_card,
                'your_hp': self.game.player1_health,
                'opponent_hp': self.game.player2_health,
                'message': p1_msg
            })
            
            send_message(self.clients[1][0], {
                'type': 'ROUND_RESULT',
                'your_card': p2_card,
                'opponent_card': p1_card,
                'your_hp': self.game.player2_health,
                'opponent_hp': self.game.player1_health,
                'message': p2_msg
            })
            
            # 檢查勝負
            if self.game.player1_health <= 0 and self.game.player2_health <= 0:
                self.broadcast({'type': 'GAME_END', 'result': 'draw'})
                print("[Duel 25 Server] Game ended in DRAW")
                break
            elif self.game.player1_health <= 0:
                send_message(self.clients[0][0], {'type': 'GAME_END', 'result': 'lose'})
                send_message(self.clients[1][0], {'type': 'GAME_END', 'result': 'win'})
                print("[Duel 25 Server] Player 2 WINS")
                break
            elif self.game.player2_health <= 0:
                send_message(self.clients[0][0], {'type': 'GAME_END', 'result': 'win'})
                send_message(self.clients[1][0], {'type': 'GAME_END', 'result': 'lose'})
                print("[Duel 25 Server] Player 1 WINS")
                break
            
            if self.game.deck:
                new_card1 = self.game.draw_card()
                new_card2 = self.game.draw_card()
                
                if new_card1:
                    self.game.player1_hand.append(new_card1)
                    send_message(self.clients[0][0], {
                        'type': 'DRAW_CARD',
                        'card': new_card1
                    })
                
                if new_card2:
                    self.game.player2_hand.append(new_card2)
                    send_message(self.clients[1][0], {
                        'type': 'DRAW_CARD',
                        'card': new_card2
                    })
            
            if len(self.game.player1_hand) == 0 or len(self.game.player2_hand) == 0:
                self.broadcast({'type': 'GAME_END', 'result': 'draw'})
                print("[Duel 25 Server] Game ended in DRAW (no cards left)")
                break

    def receive_card_choice(self, sock):
        try:
            data = recv_message(sock)
            if data and data.get('type') == 'PLAY_CARD':
                return data.get('card')
        except:
            pass
        return None
    
    def broadcast(self, data):
        for client_socket, _, _ in self.clients:
            try:
                send_message(client_socket, data)
            except:
                pass
    
    def cleanup(self):
        print("[Game Server] Cleaning up...")
        for client_socket, _, _ in self.clients:
            try:
                client_socket.close()
            except:
                pass

class Duel_25:
    def __init__(self):
        self.deck = self.create_deck()
        random.shuffle(self.deck)
        self.player1_hand = []
        self.player2_hand = []
        self.player1_health = 25
        self.player2_health = 25
        self.round_num = 0
        
    def create_deck(self):
        suits = ['Spade', 'Club', 'Diamond', 'Heart']
        deck = []
        for suit in suits:
            for value in range(1, 14):
                deck.append({'suit': suit, 'value': value})
        return deck
    
    def deal_initial_cards(self):
        self.player1_hand = [self.deck.pop() for _ in range(5)]
        self.player2_hand = [self.deck.pop() for _ in range(5)]
    
    def draw_card(self):
        if self.deck:
            return self.deck.pop()
        return None
    
    def is_black_card(self, card):
        return card['suit'] in ['Spade', 'Club']
    
    def compute_round_effects(self, p1_card, p2_card, p1_hp, p2_hp):
        p1_suit = p1_card['suit']
        p1_val = p1_card['value']
        p2_suit = p2_card['suit']
        p2_val = p2_card['value']
        
        p1_lines = []
        p2_lines = []
        
        current_p1_hp = p1_hp
        current_p2_hp = p2_hp
        
        is_p1_black = self.is_black_card(p1_card)
        is_p2_black = self.is_black_card(p2_card)
        
        if is_p1_black and is_p2_black:
            p1_lines.append("Both players used attack cards!")
            p2_lines.append("Both players used attack cards!")
            if p1_val <= p2_val:
                current_p2_hp -= p1_val
                p1_lines.append(f"You attack for {p1_val} damage! Opponent HP: {current_p2_hp}")
                p2_lines.append(f"Opponent attacks for {p1_val} damage! Your HP: {current_p2_hp}")
                if current_p2_hp > 0:
                    current_p1_hp -= p2_val
                    p1_lines.append(f"Opponent attacks for {p2_val} damage! Your HP: {current_p1_hp}")
                    p2_lines.append(f"You attack for {p2_val} damage! Opponent HP: {current_p1_hp}")
            else:
                current_p1_hp -= p2_val
                p1_lines.append(f"Opponent attacks for {p2_val} damage! Your HP: {current_p1_hp}")
                p2_lines.append(f"You attack for {p2_val} damage! Opponent HP: {current_p1_hp}")
                if current_p1_hp > 0:
                    current_p2_hp -= p1_val
                    p1_lines.append(f"You attack for {p1_val} damage! Opponent HP: {current_p2_hp}")
                    p2_lines.append(f"Opponent attacks for {p1_val} damage! Your HP: {current_p2_hp}")
        
        elif is_p1_black and p2_suit == 'Heart':
            if current_p2_hp - p1_val <= 0:
                current_p2_hp -= p1_val
                p1_lines.append(f"Your attack deals {p1_val} lethal damage! Heart card has no effect!")
                p2_lines.append(f"Opponent's attack deals {p1_val} lethal damage! Your heart has no effect!")
                p1_lines.append(f"Opponent HP: {current_p2_hp}")
                p2_lines.append(f"Your HP: {current_p2_hp}")
            else:
                current_p2_hp -= p1_val
                p1_lines.append(f"You attack for {p1_val} damage! Opponent HP: {current_p2_hp}")
                p2_lines.append(f"Opponent attacks for {p1_val} damage! Your HP: {current_p2_hp}")
                current_p2_hp += p2_val
                p1_lines.append(f"Opponent heals for {p2_val}! Opponent HP: {current_p2_hp}")
                p2_lines.append(f"You heal for {p2_val}! Your HP: {current_p2_hp}")
        
        elif is_p2_black and p1_suit == 'Heart':
            if current_p1_hp - p2_val <= 0:
                current_p1_hp -= p2_val
                p1_lines.append(f"Opponent's attack deals {p2_val} lethal damage! Your heart has no effect!")
                p2_lines.append(f"Your attack deals {p2_val} lethal damage! Heart card has no effect!")
                p1_lines.append(f"Your HP: {current_p1_hp}")
                p2_lines.append(f"Opponent HP: {current_p1_hp}")
            else:
                current_p1_hp -= p2_val
                p1_lines.append(f"Opponent attacks for {p2_val} damage! Your HP: {current_p1_hp}")
                p2_lines.append(f"You attack for {p2_val} damage! Opponent HP: {current_p1_hp}")
                current_p1_hp += p1_val
                p1_lines.append(f"You heal for {p1_val}! Your HP: {current_p1_hp}")
                p2_lines.append(f"Opponent heals for {p1_val}! Opponent HP: {current_p1_hp}")
        
        elif is_p1_black and p2_suit == 'Diamond':
            current_p1_hp -= p1_val
            p1_lines.append(f"Your attack was rebounded! You take {p1_val} damage!")
            p2_lines.append(f"You rebounded the attack! Opponent takes {p1_val} damage!")
            p1_lines.append(f"Your HP: {current_p1_hp}")
            p2_lines.append(f"Opponent HP: {current_p1_hp}")
        
        elif is_p2_black and p1_suit == 'Diamond':
            current_p2_hp -= p2_val
            p1_lines.append(f"You rebounded the attack! Opponent takes {p2_val} damage!")
            p2_lines.append(f"Your attack was rebounded! You take {p2_val} damage!")
            p1_lines.append(f"Opponent HP: {current_p2_hp}")
            p2_lines.append(f"Your HP: {current_p2_hp}")
        
        elif p1_suit == 'Heart' and p2_suit == 'Heart':
            current_p1_hp += p1_val
            current_p2_hp += p2_val
            p1_lines.append(f"Both players heal! You: +{p1_val}, Opponent: +{p2_val}")
            p2_lines.append(f"Both players heal! You: +{p2_val}, Opponent: +{p1_val}")
            p1_lines.append(f"Your HP: {current_p1_hp}, Opponent HP: {current_p2_hp}")
            p2_lines.append(f"Your HP: {current_p2_hp}, Opponent HP: {current_p1_hp}")
        
        elif p1_suit == 'Heart':
            current_p1_hp += p1_val
            p1_lines.append(f"You heal for {p1_val}! Your HP: {current_p1_hp}")
            p2_lines.append(f"Opponent heals for {p1_val}! Opponent HP: {current_p1_hp}")
        
        elif p2_suit == 'Heart':
            current_p2_hp += p2_val
            p1_lines.append(f"Opponent heals for {p2_val}! Opponent HP: {current_p2_hp}")
            p2_lines.append(f"You heal for {p2_val}! Your HP: {current_p2_hp}")
        
        else:
            p1_lines.append("No damage dealt this round.")
            p2_lines.append("No damage dealt this round.")
        
        p1_message = "\\n".join(p1_lines)
        p2_message = "\\n".join(p2_lines)
        
        return current_p1_hp, current_p2_hp, p1_message, p2_message

def main():
    port = int(sys.argv[1])
    max_players = int(sys.argv[2])

    server = GameServer(port, max_players)
    server.start()

if __name__ == '__main__':
    main()
