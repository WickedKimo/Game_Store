import socket
import json
import struct
import threading
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
import os

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


DB_HOST = "0.0.0.0"
DB_PORT = 21212

class Database:
    def __init__(self, data_file="./database.json"):
        self.data_file = data_file
        self.collections = {
            "Player": {},
            "Developer": {},
            "Game": {}
        }
        self.locks = {
            "Player": threading.Lock(),
            "Developer": threading.Lock(),
            "Game": threading.Lock()
        }
        self.next_ids = {
            "Player": 1,
            "Developer": 1,
            "Game": 1
        }
        self.load_from_file()
    
    def load_from_file(self):
        if os.path.exists(self.data_file):
            with open(self.data_file, 'r', encoding="utf-8") as f:
                data = json.load(f)
                self.collections = data.get("collections", self.collections)
                self.next_ids = data.get("next_ids", self.next_ids)
    
    def save_to_file(self):
        data = {
            "collections": self.collections,
            "next_ids": self.next_ids
        }
        with open(self.data_file, 'w', encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    
    def create(self, collection: str, data: Dict) -> Dict:
        with self.locks[collection]:
            doc_id = self.next_ids[collection]
            self.next_ids[collection] += 1
            
            document = {"id": doc_id, **data}

            # print(doc_id)
            # print(document)
            
            self.collections[collection][doc_id] = document
            self.save_to_file()
            
            return document
    
    # def read(self, collection: str, doc_id: int) -> Dict:
    #     with self.locks[collection]:
    #         document = self.collections[collection].get(doc_id)
    #         if document:
    #             return document
    #         else:
    #             return {}
    
    # def update(self, collection: str, doc_id: int, data: Dict) -> Dict:
    #     with self.locks[collection]:
    #         if doc_id in self.collections[collection]:
    #             self.collections[collection][doc_id].update(data)
    #             self.save_to_file()
    #             return {"success": True, "data": self.collections[collection][doc_id]}
    #         else:
    #             return {"success": False, "error": "Document not found"}
    
    def delete(self, collection: str, filters: Dict) -> List:
        with self.locks[collection]:
            to_delete = []
            results = []

            for doc_id, doc in self.collections[collection].items():
                match = True
                for key, value in filters.items():
                    if key not in doc or doc[key] != value:
                        match = False
                        break
                if match:
                    to_delete.append(doc_id)
                    results.append(doc)

            for doc_id in to_delete:
                del self.collections[collection][doc_id]
        self.save_to_file()
        
        return {"success": True, "data": results}
    
    def query(self, collection: str, filters: Dict) -> Dict:
        print(filters)
        with self.locks[collection]:
            results = []
            for doc in self.collections[collection].values():
                match = True
                for key, value in filters.items():
                    if key not in doc or doc[key] != value:
                        match = False
                        break
                if match:
                    results.append(doc)
            print(results)
            return results
    
    def list_all(self, collection: str) -> Dict:
        with self.locks[collection]:
            return {"success": True, "data": list(self.collections[collection].values())}


class DBServer:
    def __init__(self, host=DB_HOST, port=DB_PORT):
        self.host = host
        self.port = port
        self.db = Database()
        self.running = False
        self.server_socket = None
    
    def start(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen()
        self.running = True
        
        print(f"[DB Server] Started on {self.host}:{self.port}")
        
        while self.running:
            try:
                client_sock, client_addr = self.server_socket.accept()
                print(f"[DB Server] New connection from {client_addr}")
                
                client_thread = threading.Thread(
                    target=self.handle_client,
                    args=(client_sock, client_addr),
                    daemon=True
                )
                client_thread.start()
            except Exception as e:
                if self.running:
                    print(f"[DB Server] Error accepting connection: {e}")
    
    def handle_client(self, client_sock: socket.socket, client_addr):
        try:
            while self.running:
                request = recv_message(client_sock)
                if not request:
                    break
                
                response = self.process_request(request)
                print(response)
                send_message(client_sock, response)
                
        except Exception as e:
            print(f"[DB Server] Error handling client {client_addr}: {e}")
        finally:
            client_sock.close()
            print(f"[DB Server] Connection closed: {client_addr}")
    
    def process_request(self, request: Dict) -> Dict:
        """Process a database request"""
        try:
            collection = request.get("collection")
            action = request.get("action")
            data = request.get("data", {})

            print(request)
            
            if collection not in self.db.collections:
                return {"success": False, "error": f"Invalid collection: {collection}"}
            
            if action == "CREATE":
                print("action is create")
                return self.db.create(collection, data)
            # elif action == "READ":
            #     return self.db.read(collection, data.get("id"))
            # elif action == "UPDATE":
            #     return self.db.update(collection, data.get("id"), data.get("updates", {}))
            elif action == "DELETE":
                return self.db.delete(collection, data.get("filter", {}))
            elif action == "QUERY":
                return self.db.query(collection, data.get("filter", {}))
            # elif action == "LIST":
            #     return self.db.list_all(collection)
            else:
                return {"success": False, "error": f"Invalid action: {action}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def stop(self):
        """Stop the database server"""
        self.running = False
        if self.server_socket:
            self.server_socket.close()

def main():
    server = DBServer()
    
    try:
        server.start()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n[DB Server] Shutting down...")
        server.stop()

if __name__ == "__main__":
    main()