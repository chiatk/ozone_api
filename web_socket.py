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


async def send_puzzle_sync_result(puzzle_sync_result: List, end_heigth: int, puzzle_hash: str,  websocket: WebSocket):
    await websocket.send_text(json.dumps({"coin": puzzle_sync_result, "heigth": end_heigth, "puzzle_hash": puzzle_hash}))

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

                await get_full_coin_of_puzzle_hashes([[puzzle_hash, start_height]], \
                     ChiaSync.node_rpc_client, websocket, send_puzzle_sync_result, end_heigth=ChiaSync.peak())


        await websocket.close(code=200)
    except Exception as e:
        error_stack = traceback.format_exc()
        print(f"Unexpected error in websocket_endpoint: {e} {error_stack}")
        manager.disconnect(websocket)
        