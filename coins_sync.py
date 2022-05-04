

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
from cat_data import CatData
from chia_sync import ChiaSync
import config as settings
from chia.util.byte_types import hexstr_to_bytes
from chia.types.coin_record import CoinRecord
from chia.types.blockchain_format.sized_bytes import bytes32
import traceback
from starlette.websockets import WebSocket, WebSocketDisconnect

async def get_full_coin_of_puzzle_hashes(puzzle_hashes_data: List, full_node_client:FullNodeRpcClient,websocket: WebSocket, on_found, end_heigth: int, include_spent_coins:bool = True) :
    puzzle_hashes:List[Tuple[bytes32, int]] = []
    for puzzle_hash_hex in puzzle_hashes_data:
        touple_item :Tuple[bytes32, int] = (bytes32(bytes.fromhex(puzzle_hash_hex[0])), int(puzzle_hash_hex[1]))
        puzzle_hashes.append(touple_item)
 
    coin_records:List[CoinRecord] = []
    for puzzle_hash_item in puzzle_hashes:
        try:
            puzzle_hash, start_height = puzzle_hash_item
            if start_height == 0:
                start_height = 32
          
            records = await full_node_client.get_coin_records_by_puzzle_hash(puzzle_hash=puzzle_hash,\
            include_spent_coins=include_spent_coins,   start_height=start_height-32)
            for r in records:
                coin_records.append(r)
           
        except Exception as e:
            logger.debug(f"puzzle_hash: {puzzle_hash_item}")
            logger.exception(e)
            print(e)
            
            continue
    
    if len(coin_records) == 0:
        print(f"no coin records found for {puzzle_hashes_data[0][0]}")
        await on_found([], end_heigth, puzzle_hashes_data[0][0],  websocket) 
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
                    logger.debug(f"Without parent coin: {row.coin.parent_coin_info}")
                    await on_found([row.to_json_dict(), None], end_heigth, row.coin.puzzle_hash.hex(), websocket)  
                    continue
                parent_coin_spend: Optional[CoinSpend] = await full_node_client.get_puzzle_and_solution(parent_coin.name, parent_coin.spent_block_index)
                if parent_coin_spend is None:
                    logger.debug(f"Without parent coin spend: {row.coin.parent_coin_info}")
                    await on_found([row.to_json_dict(), None], end_heigth, row.coin.puzzle_hash.hex(),  websocket)  
                    continue   
                await  on_found([row.to_json_dict(), parent_coin_spend.to_json_dict()], end_heigth, row.coin.puzzle_hash.hex(),  websocket)  
        except Exception as e:
            logger.exception(e)
            logger.debug(row) 
            logger.exception(traceback.format_exc())
           
            continue 
  
 