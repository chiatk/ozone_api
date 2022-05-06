import asyncio
from lib2to3.pgen2.token import OP
from optparse import Option
from chia.types.blockchain_format.program import SerializedProgram, INFINITE_COST
from typing import List, Optional, Dict
from chia.wallet.puzzles.cat_loader import CAT_MOD
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
from chia_sync import get_full_node_client
import config as settings
from chia.util.byte_types import hexstr_to_bytes
from chia.types.coin_record import CoinRecord
from chia.types.blockchain_format.sized_bytes import bytes32
from starlette.websockets import WebSocket, WebSocketDisconnect


async def analice_block( node_client: FullNodeRpcClient, coin: CoinRecord,) -> bool:
    """
    El método get_block_recors devuelve el primer bloque pero no el último.
    Ejemplo si pones de 500 a 600 te devuelve hasta 599.
    reward_claims_incorporated es diferente de None, es un bloque de transacción.
    Esta función solo necesita un bloque inicial para iniciar el análisis.
    """

    confirmed_height = int(coin.confirmed_block_index)


    block_record: Optional[BlockRecord] = await node_client.get_block_record_by_height(confirmed_height)
     
            
    header_hash =  block_record.header_hash

    additions, removals = await node_client.get_additions_and_removals(header_hash)
  
    for cr in additions:
        coin_record: CoinRecord = cr
        coin_ph = coin_record.coin.puzzle_hash
        
            
        for removal in removals:
            parent_coin_info = coin_record.coin.parent_coin_info.hex()
            removal_name = removal.name.hex()
            if parent_coin_info == removal_name:
                
                return removal
                        
                                
                
            
    return None

async def get_sender_address_of_cat_coin(coin: CoinRecord, node_client: FullNodeRpcClient) -> Optional[bytes32]:

    removal_coin = await analice_block(node_client, coin)
    # address = encode_puzzle_hash(coin.coin.puzzle_hash, "xch")
    # print(f"address: {address}")
    # address2 = encode_puzzle_hash(removal_coin.coin.puzzle_hash, "xch")
    # print(f"address2: {address2}")

    parent_coin_spend: Optional[CoinSpend] = await node_client.get_puzzle_and_solution(removal_coin.name, removal_coin.spent_block_index)
    puzzle_reveal: SerializedProgram = parent_coin_spend.puzzle_reveal
    mod, curried_args = puzzle_reveal.uncurry()
    if mod == CAT_MOD:
        arguments = curried_args.as_iter()
        puzzle= arguments[2]
        puzzle_hash = puzzle.hash()
        print(parent_coin_spend)
    else:
        print(f"No es un cat coin")

async def main():
    node_client = await get_full_node_client()
    coin_name = bytes32(bytes.fromhex('3f371d3533bae975c3cd3b7e38595403c83717207139f86ff466119692865b41'))
    coin = await node_client.get_coin_record_by_name(coin_name)
    await get_sender_address_of_cat_coin(coin, node_client)
    
    



if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    try:
     
        loop.run_until_complete(main())

        loop.stop()
     
    except IOError:
        print("File not accessible")
    except Exception as e:
        print(e)

