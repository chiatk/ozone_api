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

 

WAIT_TIME = 5

async def get_full_node_client() -> FullNodeRpcClient:
    config = settings.CHIA_CONFIG
    full_node_client = await FullNodeRpcClient.create(config['self_hostname'], config['full_node']['rpc_port'],
                                                      settings.CHIA_ROOT_PATH, settings.CHIA_CONFIG)
    return full_node_client

class ChiaSync:
    blockchain_state: Dict = {}
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
        ChiaSync.task = asyncio.create_task(ChiaSync.load_state_loop())
        ChiaSync.tokens_task = asyncio.create_task(ChiaSync.load_tokens_loop())
        ChiaSync.watch_dog_task = asyncio.create_task(ChiaSync.watch_dog())

    def peak()-> BlockRecord:
        return ChiaSync.blockchain_state["peak"].height   

    async def watch_dog():
        while(True):
            dead_time =ChiaSync.last_processed + (WAIT_TIME+10) 

            if(dead_time < time.time()):
                logger.warning("ChiaSync is not responding, killing it")
                ChiaSync.close()
                try:
                    ChiaSync.state.client.close()
                except Exception as e:
                    
                    print(f"exception: {e}")
                    pass
                ChiaSync.state.client = await get_full_node_client()
                
                ChiaSync.start(ChiaSync.state)
                await asyncio.sleep(20)
            else:
                print(f"ChiaSync is alive {int(dead_time -  time.time())}")
            await asyncio.sleep(1)

    async def load_state_loop():
        while(True):
            ChiaSync.last_processed = time.time()

            try:
                ChiaSync.blockchain_state = await ChiaSync.node_rpc_client.get_blockchain_state()
                print(f"blockchain height: { ChiaSync.peak() }")
                
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


    def close():
        if ChiaSync.task is not None:
            ChiaSync.task.cancel()
            ChiaSync.task = None
    

 
 


