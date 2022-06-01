import asyncio
import json
from socket import socket
import traceback
from typing import List

from fastapi import APIRouter
 
from starlette.websockets import WebSocket, WebSocketDisconnect
from chia_sync import ChiaSync
from chia.types.blockchain_format.sized_bytes import bytes32
from coins_sync import get_full_coin_of_puzzle_hashes
 

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def send_personal_message(self, message: str, websocket: WebSocket):
        await websocket.send_text(message)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)


manager = ConnectionManager()
router = APIRouter()

loop = asyncio.get_event_loop()


async def send_puzzle_sync_result(puzzle_sync_result: List, end_heigth: int, puzzle_hash: str,  websocket: WebSocket):
    ph_32 = bytes32(bytes.fromhex(puzzle_hash))
    if ph_32 in ChiaSync.puzzle_hashes:

        item = ChiaSync.puzzle_hashes[ph_32]
        item["heigth"] = end_heigth
        ChiaSync.puzzle_hashes[ph_32] = item
            
        try:
            await websocket.send_text(json.dumps({"a":"sync", "coin": puzzle_sync_result, "heigth": end_heigth, "puzzle_hash": puzzle_hash}))
        except Exception as e:
            pass

async def send_new_block_height(peak_heigth: int):
    await manager.broadcast(json.dumps({"a":"new_block_height",   "heigth": peak_heigth}))

ChiaSync.peak_broadcast_callback= send_new_block_height

@router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket , client_id: str):
   
    await manager.connect(websocket)

    try:
        while True:
            data = await websocket.receive_json()
            action = None
            if "a" in data:
                action = data["a"]
            if action == "hello":
                await websocket.send_text(json.dumps({"a": "hello"}))

            elif action == "close":
                break
          
            elif action == "sync":
                puzzle_hash_32= bytes32(bytes.fromhex(data["puzzle_hash"]))
                puzzle_hash = data["puzzle_hash"]
                start_height = data["start_height"]
                 
               
                if puzzle_hash_32 not in ChiaSync.puzzle_hashes:
                     ChiaSync.puzzle_hashes[puzzle_hash_32] = {"sockets":[websocket], \
                         "heigth": start_height, "puzzle_hash": puzzle_hash_32, "clients": {client_id:client_id}}
                else:
                    item = ChiaSync.puzzle_hashes[puzzle_hash_32]
                    item["sockets"].append(websocket)
                    item["clients"][client_id] = client_id

                    old_heigth = item["heigth"]
                    if start_height < old_heigth:
                        item["heigth"] = old_heigth

                    ChiaSync.puzzle_hashes[puzzle_hash_32] = item

                loop.create_task (get_full_coin_of_puzzle_hashes([[puzzle_hash, start_height]], \
                     ChiaSync.node_rpc_client, websocket, send_puzzle_sync_result, end_heigth=ChiaSync.peak(), client_id=client_id))
            elif action == "sync_all":
                
                for key in ChiaSync.puzzle_hashes:
                    item = ChiaSync.puzzle_hashes[key]
                    clients_set = item["clients"]
                    if client_id in clients_set:
                        if ChiaSync.peak() > item["heigth"]:
                            element = [item["puzzle_hash"].hex(), item["heigth"]]
                            loop.create_task (get_full_coin_of_puzzle_hashes([element], \
                            ChiaSync.node_rpc_client, websocket, send_puzzle_sync_result, end_heigth=ChiaSync.peak(), client_id=client_id))
 

        await websocket.close(code=200)
    except Exception as e:
        error_stack = traceback.format_exc()
        print(f"Unexpected error in websocket_endpoint: {e} {error_stack}")
        manager.disconnect(websocket)
        items  = ChiaSync.puzzle_hashes.copy()
        for key in items:
            item = items[key]
            clients_set = item["clients"]
            if client_id in clients_set:
                
                ChiaSync.puzzle_hashes.pop(key)
                print(f"Removed client {client_id} from puzzle {key}")
              

        
