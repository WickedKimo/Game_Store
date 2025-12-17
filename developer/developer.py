import socket
import json
import base64
import time
import uuid
import struct
from pathlib import Path
from typing import Dict, Optional
import socket
import threading
from create_game_template import interactive_create

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


SERVER_HOST = "140.113.17.11"
SERVER_PORT = 26969

class DeveloperClient:
    def __init__(self, host=SERVER_HOST, port=SERVER_PORT):
        self.host = host
        self.port = port
        self.sock = None
        self.connected = False

        self.pending_requests = {}
        self.request_lock = threading.Lock()

        self.developer = {}
    
    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            self.connected = True
            self.receiver_thread = threading.Thread(target=self.receive_lobby_messages, daemon=True)
            self.receiver_thread.start()
            return True
        
        except:
            return False
    
    def disconnect(self):
        self.connected = False
        if self.sock:
            try:
                if self.developer:
                    self.send_request({'action': 'LOGOUT'})
                self.sock.close()
            except:
                pass
    
    def send_request(self, request: dict) -> dict:
        try:
            request_id = str(uuid.uuid4())
            request['requestId'] = request_id
            
            send_message(self.sock, request)
            
            timeout = 5
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                with self.request_lock:
                    if request_id in self.pending_requests:
                        response = self.pending_requests.pop(request_id)
                        return response
                time.sleep(0.01)

            return {'success': False, 'error': 'Request timeout'}
            
        except Exception as e:
            print(f"[Developer] Error sending request: {e}")
            return {'success': False, 'error': str(e)}
        
    def receive_lobby_messages(self):
        try:
            while self.connected:
                msg = recv_message(self.sock)
                if not msg:
                    break
            
                request_id = msg.get('requestId')
                if request_id:
                    with self.request_lock:
                        self.pending_requests[request_id] = msg
                
        except Exception as e:
            if self.connected:
                print(f"[Developer] Receive error: {e}")
        finally:
            self.connected = False

    def main_menu(self):
        while self.connected:
            if not self.developer:
                print("\nWelcome to K-steam")
                print("1. Register")
                print("2. Login")
                print("3. Exit")
                try:
                    choice = input("Enter choice: ").strip()
                    if choice == '1':
                        name = input("Name: ").strip()
                        password = input("Password: ").strip()
                        self.register(name, password)
                    elif choice == '2':
                        name = input("Name: ").strip()
                        password = input("Password: ").strip()
                        self.login(name, password)
                    elif choice == '3':
                        print("Exiting...")
                        break
                    else:
                        print("Invalid choice")
                except Exception as e:
                    print(f"✗ Error: {e}")

            elif self.developer:
                print(f"\n=== Developer Menu ({self.developer['userName']}) ===")
                print("1. Create Game Template")
                print("2. Upload Game")
                print("3. List My Games")
                print("4. Remove Game")
                print("0. Logout")
                
                try:
                    choice = input("\nEnter choice: ").strip()
                    
                    if choice == '1':
                        interactive_create(self.developer['userName'])
                    elif choice == '2':
                        self.upload_game()
                    elif choice == '3':
                        self.list_my_games()
                    elif choice == '4':
                        self.remove_game()
                    elif choice == '0':
                        print("Logging out...")
                        self.logout()
                except ValueError as e:
                        print(f"✗ Invalid input: {e}")
                except KeyboardInterrupt:
                    print("\n")
                    self.logout()
                    print("Exiting...")
                except Exception as e:
                    print(f"✗ Error: {e}")
    
    def register(self, name: str, password: str) -> bool:
        response = self.send_request({
            'action': 'REGISTER',
            'name': name,
            'password': password,
            "role": "Developer"
        })

        if response.get('success'):
            print(f"\n✓ Registration successful!")
            return True
        else:
            print(f"\n✗ Registration failed: {response.get('error')}")
            return False
    
    def login(self, name: str, password: str) -> bool:
        response = self.send_request({
            'action': 'LOGIN',
            'name': name,
            'password': password,
            "role": "Developer"
        })
        
        if response.get('success'):
            self.developer = response.get("data")[0]
            print(f"\n✓ Login successful! Welcome, {self.developer['userName']}")
            return True
        else:
            print(f"\n✗ Login failed: {response.get('error')}")
            return False
        
    def logout(self) -> bool:
        response = self.send_request({
            'action': 'LOGOUT',
            'name': self.developer["userName"],
            "role": "Developer"
        })
        if response.get('success'):
            print(f"✓ Logout successful! Goodbye, {self.developer['userName']}")
            self.developer = {}
            return True
        else:
            print("✗ Logout failed")
            return False
    
    def upload_game(self):
        games_dir = Path("games")
        
        game_folders = [f for f in games_dir.iterdir() if f.is_dir()]
        
        while True:
            print("\nLocal Games:")
            for i, folder in enumerate(game_folders, 1):
                print(f"{i}. {folder.name}")
            print("0. cancel")
            choice = int(input("\nSelect Game Number: ")) - 1
            if -1 <= choice <= len(game_folders):
                break
            else:
                print("Invalid Choice!")
        if choice == -1:
            return

        game_path = game_folders[choice]

        version_folders = [f for f in game_path.iterdir() if f.is_dir()]
        
        while True:
            print("\nVersions:")
            for i, folder in enumerate(version_folders, 1):
                print(f"{i}. {folder.name}")
            print("0. cancel")
            choice = int(input("\nSelect Game Version: ")) - 1
            if -1 <= choice <= len(game_folders):
                break
            else:
                print("Invalid Choice!")

        if choice == -1:
            return
        
        final_game_path = version_folders[choice]
        
        config_path = final_game_path / "game_config.json"
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        files = {}
        for file_path in final_game_path.rglob('*'):
            if file_path.is_file():
                relative_path = file_path.relative_to(final_game_path)
                with open(file_path, 'rb') as f:
                    files[str(relative_path)] = base64.b64encode(f.read()).decode('utf-8')
        
        response = self.send_request({
            'action': 'UPLOAD_GAME',
            'developer_name': self.developer["userName"],
            'game_data': config,
            'files': files
        })
        
        if response['success']:
            print("\n✓ Upload Success!")
        else:
            msg = response.get("message")
            if msg == "update":
                print(f"\n{config['name']}_v{config['version']} is already on the K-steam")
                c = input("Do you sure you want to overwrite?(Y/N): ").upper()
                while c != 'Y' and c != 'N':
                    input("Enter Y or N to continue: ").upper()
                if c == 'Y':
                    response = self.send_request({
                        'action': 'UPDATE_GAME',
                        'developer_name': self.developer["userName"],
                        'game_data': config,
                        'files': files
                    })
                    if response['success']:
                        print("\n✓ Update Success!")
                    else:
                        print("\n✗ Update Failed")
                else:
                    print("Operation Discarded")
            else:
                print("\n✗ Upload Failed")

    def list_my_games(self):
        response = self.send_request({
            'action': 'LIST_GAMES',
            'developer_name': self.developer["userName"],
        })

        if response.get("success"):
            print(f"\n=== My Games ===")
            for i, game in enumerate(response.get("data"), 1):
                print(f"{i}, {game['name']}_v{game['version']}")
        else:
            print("List fail")

    def remove_game(self):
        response = self.send_request({
            'action': 'LIST_GAMES',
            'developer_name': self.developer["userName"],
        })
        games = response.get("data")
        while True:
            print(f"\n=== My Games ===")
            for i, game in enumerate(games, 1):
                print(f"{i}, {game['name']}_v{game['version']}")
            print("0. cancel")
            choice = int(input("\nSelect one to delete: "))
            if 0 <= choice <= len(games):
                break
            else:
                print("Invalid Choice!")
        if choice == 0:
            return
        choice -= 1
        response = self.send_request({
            'action': 'REMOVE_GAME',
            'game': games[choice]["name"],
            "version" : games[choice]["version"]
        })

        if response.get("success"):
            print("Delete success")
        else:
            print("Delete fail")

def main():
    client = DeveloperClient()
    
    if not client.connect():
        print("Failed to connect to server")
        return
    
    try:
        client.main_menu()
    finally:
        client.disconnect()

if __name__ == '__main__':
    main()