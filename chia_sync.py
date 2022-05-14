import asyncio
from lib2to3.pgen2.token import OP
from optparse import Option
import os
import json
import time 
from typing import List, Optional, Dict
import requests
from logzero import logger
from fastapi import FastAPI, APIRouter, Request, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from aiocache import caches, cached
from pydantic import BaseModel
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.util.bech32m import encode_puzzle_hash, decode_puzzle_hash as inner_decode_puzzle_hash
from chia.types.spend_bundle import SpendBundle
from chia.types.coin_spend import CoinSpend
from chia.consensus.block_record import BlockRecord
from cat_data import CatData
import config as settings
from chia.util.byte_types import hexstr_to_bytes
from chia.types.coin_record import CoinRecord
from chia.types.blockchain_format.sized_bytes import bytes32
from starlette.websockets import WebSocket, WebSocketDisconnect
 

WAIT_TIME = 20

async def get_full_node_client() -> FullNodeRpcClient:
    config = settings.CHIA_CONFIG
    full_node_client = await FullNodeRpcClient.create(config['self_hostname'], config['full_node']['rpc_port'],
                                                      settings.CHIA_ROOT_PATH, settings.CHIA_CONFIG)
    return full_node_client

class ChiaSync:
    blockchain_state: Dict = {}
    puzzle_hashes: Dict = {}
    node_rpc_client: Optional[FullNodeRpcClient] = None
    task :Optional[asyncio.Task] = None
    tokens_task :Optional[asyncio.Task] = None
    watch_dog_task :Optional[asyncio.Task] = None
    tokens_list: List[CatData] = []
    last_processed: float = 0
    state = None
 
    def start(state):
        ChiaSync.node_rpc_client = state.client
        ChiaSync.state = state
        if  ChiaSync.task is not None:
            if not ChiaSync.task.cancelled():
                ChiaSync.task.cancel()
        ChiaSync.task = asyncio.create_task(ChiaSync.load_state_loop())
        ChiaSync.tokens_task = asyncio.create_task(ChiaSync.load_tokens_loop()) 

    def peak()-> BlockRecord:

        if ChiaSync.blockchain_state is not None:
            if "peak" in ChiaSync.blockchain_state:
                return ChiaSync.blockchain_state["peak"].height
        return 0

   
    async def load_state_loop():
        while(True):
            ChiaSync.last_processed = time.time()
            try:
                #last_peak = ChiaSync.peak()
                ChiaSync.blockchain_state = await ChiaSync.node_rpc_client.get_blockchain_state()
                print(f"blockchain height: { ChiaSync.peak() }")
                # if ChiaSync.peak() > last_peak:
                #     if last_peak == 0:
                #         last_peak = ChiaSync.peak() - 5
                #     asyncio.create_task(ChiaSync.puzzle_hash_tracing(last_peak, ChiaSync.peak() ))
                
            except Exception as e:
                print(f"exception: {e}")
            await asyncio.sleep(WAIT_TIME) 
    async def load_tokens_loop():
        while(True):
            try:
                r = requests.get('https://api.taildatabase.com/enterprise/tails', headers={'x-api-version':'1', 'accept':'application/json'})
                if r.status_code == 200:
                    jsonData = r.json()
                    t_list = jsonData['tails']
                    token_list: List[CatData] = []
                    for t in t_list:
                        try:
                            clvm = None
                            logo_url = None
                            chialisp = None
                            multiplier = None
                            category = None
            
                            if "logo_url" in t:
                                logo_url = t["logo_url"]
                            if "multiplier" in t:
                                multiplier = t["multiplier"]
                            if "category" in t:
                                category = t["category"]  

                            cat_data = CatData(hash=t["hash"], code=t["code"], name=t["name"],\
                               description=t["description"], multiplier=multiplier, category=category, \
                                  supply=t["supply"], hashgreen_price=t["hashgreen_price"],\
                                       hashgreen_marketcap=t["hashgreen_marketcap"], clvm=clvm,\
                                            chialisp=chialisp, logo_url=logo_url, \
                                                website_url=t["website_url"], discord_url=t["discord_url"], \
                                                    twitter_url=t["twitter_url"])
                            token_list.append(cat_data)
                        except Exception as e:
                            print(f"exception: {e}")

                    ChiaSync.tokens_list = token_list
                
            except Exception as e:
                print(f"exception: {e}")
            await asyncio.sleep(60*30)


    async def on_found(puzzle_sync_result: List, end_heigth: int, puzzle_hash: bytes32):
        if puzzle_hash in ChiaSync.puzzle_hashes:
            item = ChiaSync.puzzle_hashes[puzzle_hash]
            for socket in item['sockets']:
                 await socket.send_text(json.dumps({"coin": puzzle_sync_result, "heigth": end_heigth, "puzzle_hash": puzzle_hash}))

    async def send_alert( coin_record: CoinRecord ):
        parent_coin: Optional[CoinRecord] = await ChiaSync.node_rpc_client.get_coin_record_by_name(coin_record.coin.parent_coin_info)
        if parent_coin is None:
            logger.debug(f"Without parent coin: {coin_record.coin.parent_coin_info}")
            await ChiaSync.on_found([coin_record.to_json_dict(), None], int(coin_record.coin.confirmed_block_index), coin_record.coin.puzzle_hash)  
                
        parent_coin_spend: Optional[CoinSpend] = await ChiaSync.node_rpc_client.get_puzzle_and_solution(parent_coin.name, parent_coin.spent_block_index)
        if parent_coin_spend is None:
            logger.debug(f"Without parent coin: {coin_record.coin.parent_coin_info}")
            await ChiaSync.on_found([coin_record.to_json_dict(), None], int(coin_record.coin.confirmed_block_index), coin_record.coin.puzzle_hash)
        
        await ChiaSync.on_found([coin_record.to_json_dict(), parent_coin_spend.to_json_dict()], int(coin_record.confirmed_block_index), \
            coin_record.coin.puzzle_hash)
         
        return True
    

    async def send_msg_to_sender( coin_record: CoinRecord, removal_coin_record: CoinRecord ):
        await ChiaSync.send_alert(removal_coin_record)
        return True
        
    async def check_is_in_db( puzzle_hash: bytes32):
        return puzzle_hash in ChiaSync.puzzle_hashes


    async def puzzle_hash_tracing( start: int = 1, end: Optional[int] = None) -> bool:
        """
        El método get_block_recors devuelve el primer bloque pero no el último.
        Ejemplo si pones de 500 a 600 te devuelve hasta 599.
        reward_claims_incorporated es diferente de None, es un bloque de transacción.
        Esta función solo necesita un bloque inicial para iniciar el análisis.
        """

        if end is None:
            end = ChiaSync.peak()
    
        records: List[BlockRecord] = await ChiaSync.node_rpc_client.get_block_records(start, end)
      
        for block_record in records:
            if block_record.get('reward_claims_incorporated') is not None:
                 
                header_hash = bytes32.from_hexstr(block_record.get('header_hash'))
        
                additions, removals = await ChiaSync.node_rpc_client.get_additions_and_removals(header_hash)
                
                for cr in additions:
                    coin_record: CoinRecord = cr
                    coin_ph = coin_record.coin.puzzle_hash
                    res = await ChiaSync.check_is_in_db(coin_ph )
                    
                    if res is True:
                        await ChiaSync.send_alert(coin_record)
                    
                    for removal in removals:
                        if coin_record.coin.parent_coin_info == removal.name:
                            res = await ChiaSync.check_is_in_db(removal.coin.puzzle_hash )

                            if res is True:
                                await ChiaSync.send_msg_to_sender(coin_record, removal)
                                 
                    
                
        return False


    def close():
        if ChiaSync.task is not None:
            ChiaSync.task.cancel()
            ChiaSync.task = None
    

 
 


