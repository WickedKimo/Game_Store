import socket
import json
import subprocess
import base64
import time
import uuid
import stat
import sys
import socket
import threading
import struct
from queue import Queue
from pathlib import Path
from typing import Dict, Optional

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

SERVER_HOST = '140.113.17.11'
SERVER_PORT = 26969

class PlayerClient:
    def __init__(self, host=SERVER_HOST, port=SERVER_PORT):
        self.host = host
        self.port = port
        self.sock = None
        self.connected = False

        self.pending_requests = {}
        self.request_lock = threading.Lock()

        self.player = {}

        self.room = {}

        self.message_queue = Queue()

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
                if self.player:
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
            print(f"[Player] Error sending request: {e}")
            return {'success': False, 'error': str(e)}
        
    def receive_lobby_messages(self):
        try:
            while self.connected:
                msg = recv_message(self.sock)
                if not msg:
                    break
                
                msg_type = msg.get('action')
                
                if msg_type == 'GAME_STARTING' and msg.get("gameStarter") != self.player["userName"]:
                    self.message_queue.put(msg)
                    print(f"\n{'='*50}", flush=True)
                    print("GAME IS STARTING!", flush=True)
                    print(f"{'='*50}", flush=True)
                    print("Enter '2' to join the game: ", end="", flush=True)
                    continue
                
                request_id = msg.get('requestId')
                if request_id:
                    with self.request_lock:
                        self.pending_requests[request_id] = msg
                
        except Exception as e:
            if self.connected:
                print(f"[Player] Receive error: {e}")
        finally:
            self.connected = False
    
    def run_menu(self):
        while self.connected:
            if not self.player:
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

            if self.player:
                if not self.room:
                    print('\n' + "="*50)
                    print("LOBBY MENU")
                    print("="*50)
                    print(f"Logged in as: {self.player['userName']}")
                    print("\n1. Browse Games")
                    print("2. List Online Users")
                    print("3. List Rooms")
                    print("4. Create Room")
                    # print("5. List My Invitations")
                    print("0. Logout")
                    
                    try:
                        choice = input("\nEnter choice: ").strip()
                        
                        if choice == '1':
                            self.browse_games()

                        elif choice == '2':
                            self.list_players(invite=False)
                        
                        elif choice == '3':
                            self.list_rooms()
                        
                        elif choice == '4':
                            while True:
                                visibility = input("\nChoose visibility:\n0. Public\n1. Private\n\nEnter choice: ").strip()
                                if visibility != '0' and visibility != '1':
                                    print("Invalid choice")
                                    continue
                                else:
                                    self.create_room(visibility)
                                    break

                        # elif choice == '5':
                        #     self.list_invitations()

                        elif choice == '0':
                            print("Logging out...")
                            self.logout()
                        else:
                            print("Invalid choice")
                            
                    except ValueError as e:
                        print(f"✗ Invalid input: {e}")
                    except KeyboardInterrupt:
                        print("\n")
                        self.logout()
                        print("Exiting...")
                    except Exception as e:
                        print(f"✗ Error: {e}")
                
                elif self.room:
                    room_info = None
                    response = self.send_request({'action': 'LIST_ROOMS'})
                    if response.get('success'):
                        rooms = response.get('rooms', [])
                        for room in rooms:
                            if room['roomId'] == self.room:
                                room_info = room
                                break
                    print("="*50)
                    print(f"GAME ROOM MENU (Room_{self.room})")
                    print("="*50)
                    if room_info:
                        print(f"Host: {room_info['host']}")
                        print(f"Game: {room_info['game_name']}_v{room_info['version']}")
                        print(f"Members: {', '.join(room_info['members'])}")
                        print(f"Status: {room_info['status']}")
                    
                    print("\n1. Invite User to Room")
                    print("2. Start/Join Game")
                    print("3. Refresh room status")
                    print("4. Leave Room")

                    try:
                        choice = input("\nEnter choice: ").strip()
                        
                        if choice == '1':
                            self.list_players(invite=True)
                        
                        elif choice == '2':
                            self.join_game(room_info)

                        elif choice == '3':
                            continue
                        
                        elif choice == '4':
                            self.leave_room()
                        
                        else:
                            print("Invalid choice")

                    except KeyboardInterrupt:
                        print("\n")
                        self.leave_room()
                        self.logout()
                        print("Exiting...")
                    except Exception as e:
                        print(f"✗ Error: {e}")
                        self.leave_room()
                        self.logout()
                        print("Exiting...")
    
    def register(self, name: str, password: str) -> bool:
        response = self.send_request({
            'action': 'REGISTER',
            'name': name,
            'password': password,
            "role": "Player"
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
            "role": "Player"
        })
        
        if response.get('success'):
            self.player = response.get("data")[0]
            print(f"\n✓ Login successful! Welcome, {self.player['userName']}", end='')
            return True
        else:
            print(f"\n✗ Login failed: {response.get('error')}")
            return False
        
    def logout(self) -> bool:
        response = self.send_request({
            'action': 'LOGOUT',
            'name': self.player["userName"],
            "role": "Player"
        })
        if response.get('success'):
            print(f"✓ Logout successful! Goodbye, {self.player['userName']}")
            self.player = {}
            return True
        else:
            print("✗ Logout failed")
            return False
        
    def browse_games(self):
        response = self.send_request({
            'action': 'LIST_GAMES',
        })

        games = response.get("data")
        if response.get("success"):
            while True:
                print('\n' + "="*50)
                print("Games on K-steam")
                print("="*50)
                for i, game in enumerate(games, 1):
                    print(f"{i}, {game['name']}_v{game['version']}")
                print("0. cancel")
                choice = int(input("\nSelect a game to download: "))
                if 0 <= choice <= len(games):
                    break
                else:
                    print("Invalid Choice!")
            if choice == 0:
                return
            else:
                self.download_game(games[choice - 1])
        else:
            print("Unknown fail")

    def download_game(self, game_info):
        game_name = game_info["name"]
        version = game_info["version"]

        response = self.send_request({
            'action': 'DOWNLOAD_GAME',
            "game_name" : game_name,
            "version" : version
        })

        game_data = response['game_data']
        game_files = response['files']
        
        # 建立遊戲目錄
        game_dir = Path(self.player["userName"]) / "games" / game_data["name"] / game_data["version"]

        if game_dir.exists():
            print(f"\nYou already have {game_data['name']}_v{game_data['version']}")
            c = input("Do you sure you want to overwrite?(Y/N): ").upper()
            while c != 'Y' and c != 'N':
                input("Enter Y or N to continue: ").upper()
            if c == 'N':
                print("Operation Discarded")
                return

        game_dir.mkdir(parents=True, exist_ok=True)
        
        # 儲存檔案
        for filename, content in game_files.items():
            file_path = game_dir / filename
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(file_path, 'wb') as f:
                f.write(base64.b64decode(content))

            file_path.chmod(stat.S_IREAD)
        
        if response.get('success'):
            print(f"\n✓ Download successful!")
            return True
        else:
            print(f"\n✗ Download failed")
            return False
    
    def list_players(self, invite=False):
        response = self.send_request({'action': 'LIST_PLAYERS'})
        
        if response.get('success'):
            players = response.get('players', [])
            while True:
                print(f"\n=== Online players ({len(players)}) ===")
                for i, player in enumerate(players, start=1):
                    print(f"{i}. {player}")
                # if invite:
                #     print("0. Cancel")
                #     player_index = int(input("\nChoose a player to invite: "))
                #     if player_index > len(players) or player_index < 0:
                #         print("Invalid choice")
                #         continue
                #     elif player_index == 0:
                #         break
                #     elif players[player_index - 1] == self.player["name"]:
                #         print("You can not invite yourself")
                #         continue
                #     else:
                #         if self.invite_player(self.room, players[player_index - 1]):
                #             break
                #         else:
                #             continue
                else:
                    break
        else:
            print(f"✗ Failed to list players: {response.get('error')}")
    
    def list_rooms(self):
        response = self.send_request({'action': 'LIST_ROOMS'})
        
        if response.get('success'):
            rooms = response.get('rooms', [])
            while True:
                print(f"\n=== Rooms ({len(rooms)}) ===")
                index = 1
                for room in rooms:
                    print(
                        f"{index}. [Room_{room['roomId']}]\n"
                        f"    Host: {room['host']}\n"
                        f"    Game: {room['game_name']}_v{room['version']}\n"
                        f"    Visibility: {room['visibility']}\n"
                        f"    Players: {room['memberCount']}/{room['room_max']}\n"
                        f"    Status: {room['status']}"
                    )
                    index += 1
                if index == 1:
                    break
                print("0. Cancel")
                room_index = int(input("\nChoose a room to join: "))
                if room_index >= index or room_index < 0:
                    print("Invalid choice")
                    continue
                elif room_index == 0:
                    break
                elif rooms[room_index - 1]['visibility'] == "Private":
                    print("You can not choose a private room")
                    continue
                else:
                    game_name = rooms[room_index - 1]['game_name']
                    version = rooms[room_index - 1]['version']
                    game_path = Path(self.player["userName"]) / "games" / game_name / version
                    if not game_path.exists():
                        print(f"\nYou don't have {game_name}_v{version}")
                        c = input("Do you want to download?(Y/N): ").upper()
                        while c != 'Y' and c != 'N':
                            input("Enter Y or N to continue: ").upper()
                        if c == 'N':
                            print("Operation Discarded")
                            return
                        game_info = {"name": game_name, "version": version}
                        self.download_game(game_info)
                    if self.join_room(rooms[room_index - 1]['roomId']):
                        break
                    else:
                        continue
                    
        else:
            print(f"✗ Failed to list rooms: {response.get('error')}")
    
    def create_room(self, visibility: str):
        if visibility == '0':
            vis = "Public"
        else:
            vis = "Private"
        
        response = self.send_request({
            'action': 'LIST_GAMES',
        })

        games = response.get("data")
        while True:
            print('\n' + "="*50)
            print("Games on K-steam")
            print("="*50)
            for i, game in enumerate(games, 1):
                print(f"{i}. {game['name']}_v{game['version']}")
            print("0. cancel")
            choice = int(input("\nSelect a game to create game room: "))
            if 0 <= choice <= len(games):
                break
            else:
                print("Invalid Choice!")
        if choice == 0:
            return
        else:
            choice -= 1
            game_name = games[choice]['name']
            version = games[choice]['version']
            game_path = Path(self.player["userName"]) / "games" / game_name / version
            if not game_path.exists():
                print(f"\nYou don't have {game_name}_v{version}")
                c = input("Do you want to download?(Y/N): ").upper()
                while c != 'Y' and c != 'N':
                    input("Enter Y or N to continue: ").upper()
                if c == 'N':
                    print("Operation Discarded")
                    return
                self.download_game(games[choice])

        room_info = {
            "host": self.player["userName"],
            "visibility": vis,
            "game_name": game_name,
            "version": version
        }
        
        response = self.send_request({
            'action': 'CREATE_ROOM',
            'room_info': room_info
        })
        
        if response.get('success'):
            room_id = response.get('roomId')
            print(f"\n✓ Room created: Room_{room_id}")
            self.room = room_id
        else:
            print(f"✗ Failed to create room: {response.get('error')}")
    
    def join_room(self, room_id: str):
        response = self.send_request({
            'action': 'JOIN_ROOM',
            'player': self.player["userName"],
            'roomId': room_id
        })
        
        if response.get('success'):
            print(f"\n✓ Joined room {room_id}")
            self.room = room_id
            return True
        else:
            print(f"✗ Failed to join room: {response.get('error')}")
            return False
    
    def leave_room(self):
        response = self.send_request({
            'action': 'LEAVE_ROOM',
            'player': self.player["userName"],
            'roomId': self.room
        })
        
        if response.get('success'):
            print(f"\n✓ Left room Room_{self.room}")
            self.room = None
            return True
        else:
            print(f"\n✗ Failed to leave room: {response.get('error')}")
            return False
    
    # def invite_player(self, room_id: str, invited_player: str):
    #     response = self.send_request({
    #         'action': 'INVITE_player',
    #         'host': self.player["name"],
    #         'roomId': room_id,
    #         'invitedplayer': invited_player
    #     })
        
    #     if response.get('success'):
    #         print(f"\n✓ Invitation sent to player {invited_player}")
    #         return True
    #     else:
    #         print(f"\n✗ Failed to send invitation: {response.get('error')}")
    #         return False
    
    # def list_invitations(self):
    #     response = self.send_request({
    #         'action': 'LIST_INVITATIONS',
    #         'player': self.player["name"]
    #     })
        
    #     if response.get('success'):
    #         invitations = response.get('invitations', [])
    #         while True:
    #             print(f"\n=== Pending Invitations ({len(invitations)}) ===")
    #             index = 1
    #             for host, room_id in invitations:
    #                 print(f"{index}. {host} invite you to join {room_id}")
    #                 index += 1
    #             if index == 1:
    #                 break
    #             print("0. Cancel")
    #             inv_index = int(input("\nChoose a invitation to accept: "))
    #             if inv_index >= index or inv_index < 0:
    #                 print("Invalid choice")
    #                 continue
    #             elif inv_index == 0:
    #                 break
    #             else:
    #                 if self.accept_invitation(invitations[inv_index - 1][1]):
    #                     break
    #                 else:
    #                     continue
    #     else:
    #         print(f"✗ Failed to list invitations: {response.get('error')}")

    # def spectate_game(self):
    #     while True:
    #         response = self.send_request({'action': 'LIST_ROOMS'})
    #         if response.get('success'):
    #             rooms = response.get('rooms', [])
    #             games = [room for room in rooms if room["status"] == "playing"]    
    #             print(f"\n=== Games ({len(games)}) ===")
    #             index = 1
    #             for game in games:
    #                 print(f"{index}. [{game['roomId']}] - Host: {game['host']} - Visibility: {game['visibility']} - Players: {game['members'][0]}, {game['members'][1]}")
    #                 index += 1
    #             if index == 1:
    #                 break
    #             print("0. Cancel")
    #             game_index = int(input("\nChoose a game to spectate: "))
    #             if game_index >= index or game_index < 0:
    #                 print("Invalid choice")
    #                 continue
    #             elif game_index == 0:
    #                 break
    #             elif rooms[game_index - 1]['visibility'] == "Private":
    #                 print("You can not spectate a private game")
    #                 continue
    #             else:
    #                 if self.start_spectate(rooms[game_index - 1]['roomId']):
    #                     return True
    #                 else:
    #                     continue
    #         else:
    #             print(f"✗ Failed to list rooms: {response.get('error')}")
    
    # def accept_invitation(self, room_id: str):
    #     response = self.send_request({
    #         'action': 'ACCEPT_INVITATION',
    #         'player': self.player["name"],
    #         'roomId': room_id
    #     })
        
    #     if response.get('success'):
    #         print(f"\n✓ Accepted invitation to {room_id}")
    #         self.room = room_id
    #         return True
    
    def join_game(self, room_info):
        game_info = None

        while not self.message_queue.empty():
            try:
                msg = self.message_queue.get_nowait()
                if msg.get('action') == 'GAME_STARTING' and msg.get('roomId') == self.room:
                    game_info = msg
            except:
                break

        game_name = room_info['game_name']
        version = room_info['version']

        if not game_info:
            response = self.send_request({
                'action': 'START_GAME',
                'roomId': self.room,
                'player_name': self.player["userName"],
                "game_name": game_name,
                "version": version
            })
            
            if response.get('success'):
                game_port = response.get('gamePort')
                game_host = response.get('gameHost', self.host)
            else:
                print(f"\n{response.get('error')}")
                return False
        else:
            game_port = game_info.get('gamePort')
            game_host = game_info.get('gameHost', self.host)
        
        base_dir = Path(__file__).parent
        game_path = base_dir / self.player["userName"] / "games" / game_name / version
        game_client = game_path / "game_client.py"

        time.sleep(0.5)

        subprocess.run(
            [
                sys.executable,
                str(game_client),
                str(game_host),
                str(game_port)
            ],
            cwd=str(game_path)
        )
        
    # def connect_to_game_server(self, game_host: str, game_port: int, spectate: bool) -> bool:
    #     try:
    #         self.game_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    #         self.game_sock.connect((game_host, game_port))
            
    #         hello = {
    #             'action': 'HELLO',
    #             'player': self.player["name"],
    #             "spectate": spectate
    #         }
    #         send_message(self.game_sock, json.dumps(hello))
    #         response_str = recv_message(self.game_sock)
    #         if response_str:
    #             response = json.loads(response_str)
                
    #             if response.get('action') == 'WELCOME':
    #                 if spectate:
    #                     print(f"\n[Game] Welcome to spectate the game!")
    #                     self.game_active = True
    #                     self.game_receiver_thread = threading.Thread(
    #                         target=self.receive_game_messages,
    #                         args=(spectate,),
    #                         daemon=True
    #                     )
    #                 else:
    #                     player_id = response.get('playerId')
    #                     role = response.get('role')
    #                     print(f"\n[Game] Welcome! You are {role}, playerId: {player_id}")
    #                     self.game_active = True
    #                     self.game_receiver_thread = threading.Thread(
    #                         target=self.receive_game_messages,
    #                         args=(spectate,),
    #                         daemon=True
    #                     )
    #                 self.game_receiver_thread.start()
                    
    #                 return True
    #         return False
    #     except Exception as e:
    #         return False
        
    # def start_spectate(self, room_id: str):
    #     response = self.send_request({
    #         'action': 'SPECTATE_GAME',
    #         'roomId': room_id
    #     })
    #     if response.get("success") == True:
    #         game_info = response.get("game_info")
    #         game_port = game_info["port"]
    #         game_host = self.host
    #         if self.connect_to_game_server(game_host, game_port, True):
    #             return True
    #         else:
    #             print("✗ Failed to connect to game server")
    #             return False
    #     else:
    #         print(f"✗ Failed to spectate this game, {response.get('error')}")
    #         return False

def main():
    client = PlayerClient()
    
    if not client.connect():
        print("Failed to connect to server")
        return
    
    try:
        client.run_menu()
    finally:
        client.disconnect()

if __name__ == '__main__':
    main()