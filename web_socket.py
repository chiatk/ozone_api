import asyncio
import json
from socket import socket
import traceback
from typing import List

from fastapi import APIRouter
 
from starlette.websockets import WebSocket, WebSocketState
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
            try:
                if connection.client_state == WebSocketState.CONNECTED:
                    await connection.send_text(message)
            except Exception as e:
                pass


manager = ConnectionManager()
router = APIRouter()

loop = asyncio.get_event_loop()


async def send_puzzle_sync_result(puzzle_sync_result: List, end_heigth: int, puzzle_hash: str,  websocket: WebSocket):
    if len(puzzle_sync_result)==0:
        return
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

async def send_synced_block_height(websocket: WebSocket, peak_heigth: int, ph_str_list: List[str]):
    await manager.broadcast(json.dumps({"a":"new_synced_block_height",   "heigth": peak_heigth, "phs":ph_str_list}))

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
          
            elif action == "add_puzzlehash"  :
                puzzle_hash_32= bytes32(bytes.fromhex(data["puzzle_hash"]))
                puzzle_hash = data["puzzle_hash"]
                start_height = data["start_height"]
                 
               
                if puzzle_hash_32 not in ChiaSync.puzzle_hashes:
                    print(f"adding {client_id}_{puzzle_hash_32.hex()}")
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

            elif action == "add_puzzlehash_list"  :
                ph_list = data["list"]
                for ph_data in ph_list:
                    puzzle_hash_32 = bytes32(bytes.fromhex(ph_data["ph"]))
                    puzzle_hash = ph_data["ph"]
                    start_height = ph_data["sh"]
                    
                
                    if puzzle_hash_32 not in ChiaSync.puzzle_hashes:
                        print(f"adding {client_id}_{puzzle_hash_32.hex()}")
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
 
 
            elif action == "sync_all":
              
                try:
                    ph_str_list = []
                    peak = ChiaSync.peak()
                    puzzle_map_list = {}
                    for key in ChiaSync.puzzle_hashes:
                        item = ChiaSync.puzzle_hashes[key]
                        clients_set = item["clients"]

                        if client_id in clients_set:
                            if ChiaSync.peak() > item["heigth"]:
                                heigth = item["heigth"] 
                                element = [item["puzzle_hash"].hex(), item["heigth"]]
                                if heigth in puzzle_map_list:
                                    puzzle_map_list[heigth].append(element)
                                else:
                                    puzzle_map_list[heigth] = [element]
                    keys = puzzle_map_list.keys()                            
                    for start_height in keys:

                        ph_list =  puzzle_map_list[start_height]
                        

                        flag = True
                        next_scan: List = []
                        SIZE = 100

                        while flag:

                            if len(ph_list) > SIZE:
                                next_scan = ph_list[:SIZE]
                                ph_list = ph_list[SIZE:]
                            else:
                                next_scan = ph_list
                                flag = False

                            for ph in next_scan:
                                ph_str_list.append(ph[0])

                            print(f'Scanning for PuzzleHashes {len(next_scan)}')
                            await  (get_full_coin_of_puzzle_hashes(next_scan, \
                                ChiaSync.node_rpc_client, websocket, send_puzzle_sync_result,\
                                     end_heigth=peak, client_id=client_id, start_height=start_height))
                    print(f'Sending PuzzleHashes {len(ph_str_list)}')
                    await send_synced_block_height(websocket, peak, ph_str_list)
                    
                except Exception as e:
                    print(e)
             
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
              

        
