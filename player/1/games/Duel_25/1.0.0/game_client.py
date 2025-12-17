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
        self.hand = []
        self.my_hp = 0
        self.opponent_hp = 0
        self.running = True
        self.waiting_for_input = False
        
    def connect(self):
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.socket.connect((self.host, self.port))
            print(f"[Duel 25] Connected to {self.host}:{self.port}")
            return True
        except Exception as e:
            print(f"[Duel 25] Connection failed: {e}")
            return False
    
    def start(self):
        if not self.connect():
            return
        
        print("\n" + "="*50)
        print("🃏  DUEL 25 - CARD BATTLE GAME")
        print("="*50)
        print("RULES:")
        print("  ♠♣ Black cards = Attack")
        print("  ♥  Heart = Heal")
        print("  ♦  Diamond = Rebound attack")
        print("Goal: Reduce opponent's HP to 0 or below!")
        print("="*50 + "\n")
        
        recv_thread = threading.Thread(target=self.receive_messages, daemon=True)
        recv_thread.start()
        
        # 等待遊戲開始
        print("[Duel 25] Waiting for opponent...")
        
        # 主執行緒等待
        try:
            recv_thread.join()
        except KeyboardInterrupt:
            print("\n[Duel 25] Disconnecting...")
        finally:
            self.cleanup()

    def card_to_string(self, card):
        """將卡片轉換為可讀字串"""
        suits = {
            'Spade': '\u2660',
            'Club': '\u2663',
            'Diamond': '\033[91m\u2666\033[0m',
            'Heart': '\033[91m\u2665\033[0m'
        }
        value_names = {1: 'A', 11: 'J', 12: 'Q', 13: 'K'}
        value_str = value_names.get(card['value'], str(card['value']))
        return f"{suits[card['suit']]}-{value_str}"
    
    def display_hand(self):
        """顯示手牌"""
        print("\n=== Your Hand ===")
        for i, card in enumerate(self.hand):
            print(f"{i+1}. {self.card_to_string(card)} (Value: {card['value']})")
    
    def receive_messages(self):
        """接收伺服器訊息"""
        while self.running:
            try:
                msg = recv_message(self.socket)
                if not msg:
                    print("\n[Duel 25] Connection lost")
                    self.running = False
                    break
                
                self.handle_message(msg)
                
            except Exception as e:
                print(f"\n[Duel 25] Receive error: {e}")
                self.running = False
                break
    
    def handle_message(self, data):
        # print(data)
        msg_type = data.get('type')
        
        if msg_type == 'HELLO':
            self.player_id = data.get('player_id')
            print(f"[Duel 25] You are Player {self.player_id}")
            
        elif msg_type == 'GAME_START':
            self.hand = data.get('your_hand', [])
            self.my_hp = data.get('your_hp')
            self.opponent_hp = data.get('opponent_hp')
            deck_size = data.get('deck_size')
            
            print("\n" + "="*50)
            print("⚔️  GAME START!")
            print("="*50)
            print(f"Your HP: {self.my_hp}")
            print(f"Opponent HP: {self.opponent_hp}")
            print(f"Cards in deck: {deck_size}")
            print("="*50)
            
        elif msg_type == 'ROUND_START':
            round_num = data.get('round')
            deck_size = data.get('deck_size')
            
            print("\n" + "="*50)
            print(f"ROUND {round_num}")
            print("="*50)
            print(f"Your HP: {self.my_hp} | Opponent HP: {self.opponent_hp}")
            print(f"Cards in deck: {deck_size}")
            
            self.display_hand()
            self.prompt_card_choice()
            
        elif msg_type == 'ROUND_RESULT':
            your_card = data.get('your_card')
            opponent_card = data.get('opponent_card')
            self.my_hp = data.get('your_hp')
            self.opponent_hp = data.get('opponent_hp')
            message = data.get('message')
            
            print(f"\nYou played: {self.card_to_string(your_card)}")
            print(f"Opponent played: {self.card_to_string(opponent_card)}")
            print(f"\n{message}")
            
        elif msg_type == 'DRAW_CARD':
            new_card = data.get('card')
            self.hand.append(new_card)
            print(f"\nYou drew: {self.card_to_string(new_card)}")
            
        elif msg_type == 'GAME_END':
            result = data.get('result')
            print("\n" + "="*50)
            if result == 'win':
                print("🎉 YOU WIN! 🎉")
            elif result == 'lose':
                print("💀 YOU LOSE!")
            else:
                print("🤝 DRAW!")
            print("="*50 + "\n")
            self.running = False
            
        else:
            print(f"[Duel 25] Unknown message: {data}")
    
    def prompt_card_choice(self):
        self.waiting_for_input = True
        
        while self.waiting_for_input and self.running:
            try:
                choice = input("\nChoose a card (1-5): ").strip()
                card_num = int(choice)
                
                if 1 <= card_num <= len(self.hand):
                    selected_card = self.hand[card_num - 1]
                    self.hand.remove(selected_card)

                    send_message(self.socket, {
                        'type': 'PLAY_CARD',
                        'card': selected_card
                    })
                    
                    self.waiting_for_input = False
                    break
                else:
                    print("Invalid choice! Please choose 1-5.")
                    
            except ValueError:
                print("Please enter a number!")
            except KeyboardInterrupt:
                self.cleanup()
            except Exception as e:
                print(f"Error: {e}")
                self.cleanup()
    
    def cleanup(self):
        self.running = False
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
        print("[Game Client] Disconnected")

def main():
    host = sys.argv[1]
    port = int(sys.argv[2])
    
    client = GameClient(host, port)
    client.start()

if __name__ == '__main__':
    main()
