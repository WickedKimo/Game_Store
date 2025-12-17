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
        
        # Game state
        self.grid_size = 5  # 5x5 dots = 4x4 boxes
        # horizontal_lines[row][col] connects dot(row, col) to dot(row, col+1)
        self.horizontal_lines = [[False] * (self.grid_size - 1) for _ in range(self.grid_size)]
        # vertical_lines[row][col] connects dot(row, col) to dot(row+1, col)
        self.vertical_lines = [[False] * self.grid_size for _ in range(self.grid_size - 1)]
        self.boxes = [[0] * (self.grid_size - 1) for _ in range(self.grid_size - 1)]  # 0 = unclaimed, 1/2 = player id
        self.scores = {1: 0, 2: 0}
        self.current_player = 1
        
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
            
            # 所有玩家已連線,開始遊戲
            if len(self.clients) == self.max_players:
                print(f"[Game Server] All players connected. Starting game...")
                self.run_game()
                
        except KeyboardInterrupt:
            print("[Game Server] Shutting down...")
        finally:
            self.cleanup()
            server_socket.close()
    
    def run_game(self):
        # Broadcast game start
        start_msg = {
            'type': 'GAME_START',
            'grid_size': self.grid_size,
            'current_player': self.current_player
        }
        self.broadcast(start_msg)
        
        # Game loop
        while self.running:
            try:
                # Get move from current player
                current_client = self.clients[self.current_player - 1]
                client_socket = current_client[0]
                
                # Request move
                move_request = {
                    'type': 'YOUR_TURN',
                    'player_id': self.current_player
                }
                send_message(client_socket, move_request)
                
                # Wait for move
                move_msg = recv_message(client_socket)
                if not move_msg or move_msg.get('type') != 'MOVE':
                    print(f"[Game Server] Invalid move from player {self.current_player}")
                    continue
                
                # Process move
                line_type = move_msg.get('line_type')  # 'horizontal' or 'vertical'
                row = move_msg.get('row')
                col = move_msg.get('col')
                
                if not self.is_valid_move(line_type, row, col):
                    error_msg = {
                        'type': 'INVALID_MOVE',
                        'message': 'Invalid move'
                    }
                    send_message(client_socket, error_msg)
                    continue
                
                # Apply move
                completed_boxes = self.apply_move(line_type, row, col, self.current_player)
                
                # Change turn only if no box was completed
                next_player = self.current_player
                if completed_boxes == 0:
                    next_player = 3 - self.current_player  # Toggle between 1 and 2
                
                # Broadcast game state with the correct next player
                state_msg = {
                    'type': 'GAME_STATE',
                    'horizontal_lines': self.horizontal_lines,
                    'vertical_lines': self.vertical_lines,
                    'boxes': self.boxes,
                    'scores': self.scores,
                    'current_player': next_player,
                    'last_move': {
                        'player': self.current_player,
                        'line_type': line_type,
                        'row': row,
                        'col': col,
                        'completed_boxes': completed_boxes
                    }
                }
                self.broadcast(state_msg)
                
                # Check if game is over
                if self.is_game_over():
                    winner = 1 if self.scores[1] > self.scores[2] else (2 if self.scores[2] > self.scores[1] else 0)
                    end_msg = {
                        'type': 'GAME_OVER',
                        'winner': winner,
                        'scores': self.scores
                    }
                    self.broadcast(end_msg)
                    print(f"[Game Server] Game over! Winner: Player {winner if winner else 'Draw'}")
                    break
                
                # Update current player
                self.current_player = next_player
                    
            except Exception as e:
                print(f"[Game Server] Error: {e}")
                break

    def is_valid_move(self, line_type, row, col):
        try:
            if line_type == 'horizontal':
                if row < 0 or row >= self.grid_size or col < 0 or col >= self.grid_size - 1:
                    return False
                return not self.horizontal_lines[row][col]
            elif line_type == 'vertical':
                if row < 0 or row >= self.grid_size - 1 or col < 0 or col >= self.grid_size:
                    return False
                return not self.vertical_lines[row][col]
        except:
            return False
        return False

    def apply_move(self, line_type, row, col, player_id):
        # Draw the line
        if line_type == 'horizontal':
            self.horizontal_lines[row][col] = True
        else:
            self.vertical_lines[row][col] = True
        
        # Check for completed boxes
        completed_boxes = 0
        boxes_to_check = []
        
        if line_type == 'horizontal':
            # Horizontal line at row is between dot rows row and row+1
            # Check box above (at box_row = row-1)
            if row > 0:
                boxes_to_check.append((row - 1, col))
            # Check box below (at box_row = row)
            if row < len(self.boxes):
                boxes_to_check.append((row, col))
        else:  # vertical
            # Vertical line at col is between dot cols col and col+1
            # Check box to the left (at box_col = col-1)
            if col > 0:
                boxes_to_check.append((row, col - 1))
            # Check box to the right (at box_col = col)
            if col < len(self.boxes[0]):
                boxes_to_check.append((row, col))
        
        for box_row, box_col in boxes_to_check:
            if self.is_box_complete(box_row, box_col) and self.boxes[box_row][box_col] == 0:
                self.boxes[box_row][box_col] = player_id
                self.scores[player_id] += 1
                completed_boxes += 1
        
        return completed_boxes

    def is_box_complete(self, row, col):
        # Check all four sides of the box
        top = self.horizontal_lines[row][col]
        bottom = self.horizontal_lines[row + 1][col]
        left = self.vertical_lines[row][col]
        right = self.vertical_lines[row][col + 1]
        return top and bottom and left and right

    def is_game_over(self):
        total_boxes = (self.grid_size - 1) * (self.grid_size - 1)
        return self.scores[1] + self.scores[2] == total_boxes

    def broadcast(self, data):
        for client_socket, _, _ in self.clients:
            try:
                send_message(client_socket, data)
            except Exception as e:
                print(f"[Game Server] Error broadcasting to client: {e}")
    
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