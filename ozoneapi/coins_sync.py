

from ast import List
import os
import json
from typing import List, Optional, Dict, Tuple
import logzero
from logzero import logger
from fastapi import FastAPI, APIRouter, Request, Body, Depends, HTTPException
from fastapi.responses import JSONResponse
from aiocache import caches, cached
from pydantic import BaseModel
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.util.bech32m import encode_puzzle_hash, decode_puzzle_hash as inner_decode_puzzle_hash
from chia.types.spend_bundle import SpendBundle
from chia.types.coin_spend import CoinSpend
from ozoneapi.cat_data import CatData
from ozoneapi.chia_sync import ChiaSync
import ozoneapi.config as settings
from chia.util.byte_types import hexstr_to_bytes
from chia.types.coin_record import CoinRecord
from chia.types.blockchain_format.sized_bytes import bytes32
import traceback
from starlette.websockets import WebSocket, WebSocketDisconnect

from ozoneapi.sync import handle_coin
 
 

async def get_full_coin_of_puzzle_hashes(puzzle_hashes_data: List, full_node_client:FullNodeRpcClient,websocket: WebSocket, on_found, end_heigth: int, include_spent_coins:bool = True, client_id:str = "", start_height=0) :
    puzzle_hashes:List[bytes32] = []
    for puzzle_hash_hex in puzzle_hashes_data:
        #touple_item :Tuple[bytes32, int] = (bytes32(bytes.fromhex(puzzle_hash_hex[0])), int(puzzle_hash_hex[1]))
        puzzle_hashes.append(bytes32(bytes.fromhex(puzzle_hash_hex[0])))
 
    coin_records:List[CoinRecord] = []

    start_height_1 = start_height - 32
    if start_height_1 <0:
        start_height_1 = 0

    coin_records = await full_node_client.get_coin_records_by_puzzle_hashes(puzzle_hashes, \
        include_spent_coins=include_spent_coins, start_height=start_height_1)
    
    
    if len(coin_records) == 0:
        print(f"no coin records found for {puzzle_hashes_data[0][0]} {client_id}")
        #await on_found([], end_heigth, puzzle_hashes_data[0][0],  websocket) 
        return   
    for row in coin_records:
        try:
            if row is None:
                logger.debug(f"row is None")
                continue
            if row.spent and include_spent_coins == False:
                 continue
           
            else:
                
                parent_coin: Optional[CoinRecord] = await full_node_client.get_coin_record_by_name(row.coin.parent_coin_info)
                if parent_coin is None:
                    logger.debug(f"Without parent coin: {row.coin.parent_coin_info} {client_id}")
                    await on_found([row.to_json_dict(), None], end_heigth, row.coin.puzzle_hash.hex(), websocket)  
                    continue
                parent_coin_spend: Optional[CoinSpend] = await full_node_client.get_puzzle_and_solution(parent_coin.name, parent_coin.spent_block_index)
                if parent_coin_spend is None:
                    logger.debug(f"Without parent coin spend: {row.coin.parent_coin_info} {client_id}")
                    await on_found([row.to_json_dict(), None], end_heigth, row.coin.puzzle_hash.hex(),  websocket)  
                    continue 
                address = encode_puzzle_hash(row.coin.puzzle_hash, "xch")  
                assets = await handle_coin(address,row, parent_coin_spend )
                if assets is not None and len(assets)>0:
                    print("tenemos assets")
                await  on_found([row.to_json_dict(), parent_coin_spend.to_json_dict()], end_heigth, row.coin.puzzle_hash.hex(),  websocket)  
        except Exception as e:
            logger.exception(e)
            logger.debug(row) 
            logger.exception(traceback.format_exc())
           
            continue 
  
 

async def get_full_coin_by_name(coin_id: bytes32, full_node_client:FullNodeRpcClient ) :
   

    coin_record:Optional[CoinRecord] = await full_node_client.get_coin_record_by_name   (coin_id)
     
    if coin_record is None:
        print(f"Coin not found {coin_id.hex()}")
        return None
   
    try:
        parent_coin: Optional[CoinRecord] = await full_node_client.get_coin_record_by_name(coin_record.coin.parent_coin_info)
        if parent_coin is None:
            logger.debug(f"Without parent coin: {coin_record.coin.parent_coin_info} ")
            return [coin_record.to_json_dict(), None]
             
        parent_coin_spend: Optional[CoinSpend] = await full_node_client.get_puzzle_and_solution(parent_coin.name, parent_coin.spent_block_index)
        if parent_coin_spend is None:
            logger.debug(f"Without parent coin spend: {coin_record.coin.parent_coin_info}  ") 
            return [coin_record.to_json_dict(), None]
                
        
        return [coin_record.to_json_dict(), parent_coin_spend.to_json_dict()]
    except Exception as e:
        logger.exception(e)
        logger.debug(coin_record) 
        logger.exception(traceback.format_exc())
        
        return None 
  
 