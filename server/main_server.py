import socket
import threading
import struct
import time
import hashlib
import subprocess
import shutil
import base64
import json
import sys
from typing import Dict, List, Optional
from pathlib import Path

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


DB_HOST = "localhost"
DB_PORT = 21212

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 26969

class DBClient:
    def __init__(self, host=DB_HOST, port=DB_PORT):
        self.host = host
        self.port = port
        self.socket = None

    def send_request(self, request: Dict) -> Dict:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((self.host, self.port))
            print(request)
            send_message(sock, request)
            response = recv_message(sock)
            sock.close()
            return response
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # def update_user(self, name: str, updates: Dict) -> Dict:
    #     return self._send_request({
    #         'collection': 'Users',
    #         'action': 'update',
    #         'data': {
    #             'name': name,
    #             'updates': updates
    #         }
    #     })
    

class MainServer:
    def __init__(self, host=SERVER_HOST, port=SERVER_PORT):
        self.host = host
        self.port = port
        self.db = DBClient()

        # self.game_manager = GameManager(self.db)
        self.online_players = {}
        self.player_lock = threading.Lock()
        self.online_developers = {}
        self.developer_lock = threading.Lock()

        self.next_room_id = 1
        self.rooms = {}
        self.room_lock = threading.Lock()

        self.next_game_port = 44848

        self.games = {}
        self.game_lock = threading.Lock()
        
    def start(self):
        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((self.host, self.port))
        server_socket.listen()
        print(f"Server listening on {self.host}:{self.port}")
        
        while True:
            client_sock, client_addr = server_socket.accept()
            thread = threading.Thread(
                target=self.handle_client, 
                args=(client_sock,),
                daemon=True
            )
            thread.start()
    
    def handle_client(self, client_sock: socket.socket):
        current_user = None
        try:
            while True:
                request = recv_message(client_sock)
                if not request:
                    break
                
                response = self.process_request(request, client_sock)
                if request.get('action') == 'LOGIN' and response:
                    current_user = response.get('userName')
                
                send_message(client_sock, response)
        finally:
            if current_user:
                with self.player_lock:
                    if current_user in self.online_players:
                        del self.online_players[current_user]
                with self.developer_lock:
                    if current_user in self.online_developers:
                        del self.online_developers[current_user]
            client_sock.close()
    
    def process_request(self, request, client_sock):
        action = request.get('action')
        request_id = request.get('requestId')
        response = {}

        print(request)
        
        # 帳號相關
        if action == 'REGISTER':
            response = self.register(request)
        elif action == 'LOGIN':
            response = self.login(request, client_sock)
        elif action == 'LOGOUT':
            response = self.logout(request)
        
        # # 開發者功能
        elif action == 'UPLOAD_GAME':
            response = self.upload_game(request)
        elif action == 'UPDATE_GAME':
            response = self.update_game(request)
        elif action == 'REMOVE_GAME':
            response = self.remove_game(request)
        
        # # 玩家功能
        elif action == 'LIST_GAMES':
            response = self.list_games(request)
        elif action == 'LIST_PLAYERS':
            response = self.list_players()
        # elif action == 'get_game_info':
        #     response = self.get_game_info(request)
        elif action == 'DOWNLOAD_GAME':
            response = self.download_game(request)
        # elif action == 'rate_game':
        #     response = self.rate_game(request)
        
        # # 房間功能
        elif action == 'CREATE_ROOM':
            response = self.create_room(request)
        elif action == 'JOIN_ROOM':
            response = self.join_room(request)
        elif action == 'LIST_ROOMS':
            response = self.list_rooms()
        elif action == "LEAVE_ROOM":
            response = self.leave_room(request)
        elif action == 'START_GAME':
            response = self.start_game(request)
        
        else:
            response = {'status': 'error', 'message': 'Unknown action'}
        
        if request_id:
            response['requestId'] = request_id
        
        return response
        
    def register(self, request: Dict):
        name = request.get('name')
        password = request.get('password')
        role = request.get("role")
        
        existing = self.db.send_request({
            'collection': role,
            'action': 'QUERY',
            'data': {"filter": {"userName": name}}
        })

        if existing[0]:
            return {'success': False, 'error': 'Username already registered'}
        
        password_hash = hashlib.sha256(password.encode()).hexdigest()

        if role == "Player":
            response = self.db.send_request({
                'collection': role,
                'action': 'CREATE',
                'data': {
                    "userName": name,
                    'passwordHash': password_hash,
                    'games_played': [],
                }
            })
        elif role == "Developer":
            response = self.db.send_request({
                'collection': role,
                'action': 'CREATE',
                'data': {
                    "userName": name,
                    'passwordHash': password_hash,
                }
            })

        if response:
            return {'success': True}
        else:
            return {'success': False, 'error': response.get('error', 'Registration failed')}
        
    def login(self, request: Dict, client_sock: socket.socket):
        name = request.get('name')
        password = request.get('password')
        role = request.get("role")

        if name in self.online_players:
            return {'success': False, 'error': 'User already online'}
        
        user = self.db.send_request({
            'collection': role,
            'action': 'QUERY',
            'data': {"filter": {"userName": name}}
        })

        if not user:
            return {'success': False, 'error': 'User not found'}
        
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        if user[0]['passwordHash'] != password_hash:
            return {'success': False, 'error': 'Invalid password'}
        
        if role == "Player":
            with self.player_lock:
                self.online_players[name] = client_sock
        elif role == "Developer":
            with self.developer_lock:
                self.online_developers[name] = client_sock
        
        return {
            'success': True,
            "data": user,
        }
    
    def logout(self, request: Dict):
        name = request.get('name')
        role = request.get("role")
        if role == "Player":
            if self.online_players[name]:
                with self.player_lock:
                    del self.online_players[name]
                return {'success': True}
        elif role == "Developer":
            if self.online_developers[name]:
                with self.developer_lock:
                    del self.online_developers[name]
                return {'success': True}
        return {'success': False}
        
    def upload_game(self, request):
        developer_name = request['developer_name']
        game_data = request['game_data']
        game_files = request['files']  # Base64 encoded files

        game = self.db.send_request({
                'collection': "Game",
                'action': 'QUERY',
                'data': {"filter": {"name": game_data["name"], "version": game_data["version"]}}
        })
        
        if game:
            return {'success': False, "message": "update"}
        
        # 建立遊戲目錄
        game_dir = Path("games") / game_data["name"] / game_data["version"]
        game_dir.mkdir(parents=True, exist_ok=True)
        
        # 儲存檔案
        for filename, content in game_files.items():
            file_path = game_dir / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'wb') as f:
                f.write(base64.b64decode(content))
        
        # 儲存遊戲資訊到資料庫
        game_info = {
            'name': game_data['name'],
            'developer_name': developer_name,
            'version': game_data['version'],
            'ratings': {},
            'average_rating': 0.0
        }
        
        response = self.db.send_request({
            'collection': "Game",
            'action': 'CREATE',
            'data': game_info
        })
        
        if response:
            return {'success': True}
        else:
            return {'success': False}
        
    def update_game(self, request):
        game_data = request['game_data']
        game_files = request['files']  # Base64 encoded files

        # 建立遊戲目錄
        game_dir = Path("games") / game_data["name"] / game_data["version"]
        
        # 儲存檔案
        for filename, content in game_files.items():
            file_path = game_dir / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'wb') as f:
                f.write(base64.b64decode(content))
        
        return {'success': True}

    def list_games(self, request):
        try:
            author = request.get("developer_name")
            if author:
                filt = {"developer_name": author}
            else:
                filt = {}
            games = self.db.send_request({
                'collection': "Game",
                'action': 'QUERY',
                'data': {"filter": filt}
            })

            return {"success" : True, "data": games}
        except Exception as e:
            print(f"Failed, error: {e}")
            return {"success" : False}
    
    def remove_game(self, request):
        game_name = request.get("game")
        version = request.get("version")
        response = self.db.send_request({
                'collection': "Game",
                'action': 'DELETE',
                'data': {"filter": {"name": game_name, "version": version}}
        })

        game_dir = Path("games") / game_name / version

        try:
            if game_dir.exists():
                shutil.rmtree(game_dir)
            else:
                print(f"[WARN] Game directory not found: {game_dir}")
        except Exception as e:
            print(f"[ERROR] Failed to delete game files: {e}")
            return {"success": False, "error": "Game deleted from DB, but file removal failed"}

        return {"success": True}
    
    def download_game(self, request):
        game_name = request.get("game_name")
        version = request.get("version")

        game_path = Path("games") / game_name / version
        
        config_path = game_path / "game_config.json"
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        files = {}
        for file_path in game_path.rglob('*'):
            if file_path.is_file():
                if file_path.name == "game_server.py":
                    continue
                relative_path = file_path.relative_to(game_path)
                with open(file_path, 'rb') as f:
                    files[str(relative_path)] = base64.b64encode(f.read()).decode('utf-8')
        
        response = ({
            'success': True,
            'game_data': config,
            'files': files
        })

        return response
    
    def list_players(self):
        try:
            with self.player_lock:
                players = list(self.online_players.keys())
            return {'success': True, 'players': players}
        except Exception as e:
            print(f"Failed, error: {e}")
            return {"success" : False}
        
    def create_room(self, reqeust):
        room_info = reqeust.get("room_info")
        host = room_info['host']
        room_visibility = room_info['visibility']
        game_name = room_info['game_name']
        version = room_info['version']

        config_path = Path("games") / game_name / version / "game_config.json"
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        with self.room_lock:
            room_id = self.next_room_id
            self.next_room_id += 1
            
            self.rooms[room_id] = {
                'host': host,
                'game_name': game_name,
                'version': version,
                'visibility': room_visibility,
                'members': [host],
                'room_max': config["max_players"],
                "room_min": config["min_players"],
                'status': 'idle'
            }
        
        return {"success": True, "roomId": room_id}
    
    def list_rooms(self) -> Dict:
        with self.room_lock:
            rooms = [
                {
                    'roomId': room_id,
                    'host': room['host'],
                    'game_name': room["game_name"],
                    'version': room["version"],
                    'visibility': room['visibility'],
                    'members': room['members'],
                    'memberCount': len(room['members']),
                    'room_max': room["room_max"],
                    'room_min': room["room_min"],
                    'status': room['status']
                }
                for room_id, room in self.rooms.items()
            ]
        return {'success': True, 'rooms': rooms}
    
    def join_room(self, message: Dict) -> Dict:
        player_name = message.get('player')
        room_id = message.get('roomId')
        
        if len(self.rooms[room_id].get('members', [])) >= self.rooms[room_id]["room_max"]:
            return {'success': False, 'error': 'Room is full'}
        
        if player_name not in self.rooms[room_id].get('members', []):
            self.rooms[room_id]['members'].append(player_name)
        
        return {'success': True, 'message': 'Joined room'}
    
    def leave_room(self, message: Dict) -> Dict:
        player_name = message.get('player')
        room_id = message.get('roomId')
        with self.room_lock:
            if room_id not in self.rooms:
                return {'success': False, 'error': 'Room not found'}
            
            room = self.rooms[room_id]
            
            if player_name in room['members']:
                room['members'].remove(player_name)
                
                if len(room['members']) == 0:
                    del self.rooms[room_id]
                elif player_name == room["host"]:
                    room["host"] = room["members"][0]
        
        return {'success': True, 'message': 'Left room'}
    
    # def handle_invite_user(self, message: Dict) -> Dict:
    #     host = message.get("host")
    #     room_id = message.get("roomId")
    #     invited_user = message.get("invitedUser")
        
    #     with self.invite_lock:
    #         if invited_user not in self.invitations:
    #             self.invitations[invited_user] = []
    #         if room_id not in self.invitations[invited_user]:
    #             self.invitations[invited_user].append([host, room_id])
        
    #     return {'success': True, 'message': 'Invitation sent'}
    
    # def handle_list_invitations(self, message: Dict) -> Dict:
    #     player_name = message.get("user")
        
    #     with self.invite_lock:
    #         invites = self.invitations.get(player_name, [])
        
    #     return {'success': True, 'invitations': invites}
    
    # def handle_accept_invitation(self, message: Dict) -> Dict:
    #     player_name = message.get('user')
    #     room_id = message.get('roomId')
        
    #     with self.invite_lock:
    #         if player_name in self.invitations:
    #             for invitation in self.invitations[player_name]:
    #                 if invitation[1] == room_id:
    #                     self.invitations[player_name].remove(invitation)
        
    #     return self.handle_join_room({"user": player_name, "roomId": room_id})
    
    def start_game(self, message: Dict) -> Dict:
        room_id = message.get('roomId')
        player_name = message.get('player_name')
        game_name = message.get("game_name")
        version = message.get("version")
        
        with self.room_lock:
            room = self.rooms[room_id]
            if player_name != room["host"]:
                return {'success': False, 'error': "Only host can start the game\n"}

            if len(room["members"]) < room["room_min"]:
                return {'success': False, 'error': f"Need at least {room['room_min']} players to start\n"}
            
            if room['status'] == 'playing':
                return {'success': False, 'error': 'Game is starting, please wait'}
            
            game_port = self.next_game_port
            self.next_game_port += 1
            room['status'] = 'playing'
        

        base_dir = Path(__file__).parent
        game_path = base_dir / "games" / game_name / version
        game_server = game_path / "game_server.py"
        lobby_host = "140.113.17.11"
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    str(game_server),
                    str(game_port),
                    str(len(room["members"]))
                ],
                cwd=str(game_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            with self.game_lock:
                self.games[room_id] = {
                    'port': game_port,
                    'process': process,
                    'members': room["members"]
                }
            
            # 啟動獨立執行緒等待遊戲結束
            wait_thread = threading.Thread(
                target=self.wait_for_game_end,
                args=(room_id, process),
                daemon=True
            )
            wait_thread.start()
            
            self.notify_room_members(room_id, {
                'action': 'GAME_STARTING',
                'gameStarter': player_name,
                'gamePort': game_port,
                'gameHost': lobby_host,
                'roomId': room_id
            })
            
            return {
                'success': True,
                'gamePort': game_port,
                'gameHost': lobby_host,
                'message': 'Game server started'
            }
            
        except Exception as e:
            with self.room_lock:
                if room_id in self.rooms:
                    self.rooms[room_id]['status'] = 'idle'
            return {'success': False, 'error': f'Failed to start game server: {e}'}
        
    def notify_room_members(self, room_id: str, message: dict):
        with self.room_lock:
            if room_id not in self.rooms:
                return
            members = self.rooms[room_id]['members'].copy()
        
        with self.player_lock:
            for member in members:
                try:
                    sock = self.online_players[member]
                    send_message(sock, message)
                except Exception as e:
                    print(f"[Lobby] Failed to notify {member}: {e}")
    
    def wait_for_game_end(self, room_id, process):
        try:
            exit_code = process.wait()
            print(f"[Game] Room {room_id} game ended with exit code {exit_code}")
            
            stdout, stderr = process.communicate()
            if stderr:
                print(f"[Game] stderr: {stderr.decode()}")
            
        except Exception as e:
            print(f"[Game] Error waiting for game end: {e}")
        
        finally:
            self.cleanup_game(room_id)

    def cleanup_game(self, room_id):
        with self.game_lock:
            if room_id in self.games:
                del self.games[room_id]
                print(f"[Cleanup] Game server for room {room_id} removed")
        
        with self.room_lock:
            if room_id in self.rooms:
                self.rooms[room_id]['status'] = 'idle'
                print(f"[Cleanup] Room {room_id} status reset to idle")

    # def stop(self):
    #     self.running = False
    #     with self.game_lock:
    #         for _, game_info in list(self.game_servers.items()):
    #             process = game_info['process']
    #             if process.poll() is None:
    #                 process.terminate()
    #                 try:
    #                     process.wait(timeout=5)
    #                 except:
    #                     process.kill()
        
    #     if self.server_socket:
    #         self.server_socket.close()

def main():
    server = MainServer()
    
    try:
        server.start()
    finally:
        print("\n[MAIN Server] Shutting down...")
        server.stop()


if __name__ == '__main__':
    main()