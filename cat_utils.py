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
 

async def get_sender_puzzle_hash_of_cat_coin(coin_record: CoinRecord, node_client: FullNodeRpcClient) -> Optional[bytes32]:
    """
    Get the puzzle hash of the sender of the cat coin.
    First obtain the parent coin, then, get the parent coin spend.
    When the coin spend is found, get the puzzle_reveal, uncurry it, get the mod and the arguments
    get the arguments, take the second argument and get the puzzle hash of the sender.

    """

    parent_coin: Optional[CoinRecord] = await node_client.get_coin_record_by_name(coin_record.coin.parent_coin_info)
    parent_coin_spend: Optional[CoinSpend] = await node_client.get_puzzle_and_solution(parent_coin.name, parent_coin.spent_block_index)
    puzzle_reveal: SerializedProgram = parent_coin_spend.puzzle_reveal
    mod, curried_args = puzzle_reveal.uncurry()
    if mod == CAT_MOD:
        arguments = list(curried_args.as_iter())
        puzzle= arguments[2]
        puzzle_hash = puzzle.get_tree_hash()
        return puzzle_hash
      
    else:
        print(f"{coin_record.coin.name.hex()} is not a cat coin")
        
    return None

async def main():
    node_client = await get_full_node_client()
    coin_name = bytes32(bytes.fromhex('4743474f3bcd85039b6c4c98d94ceaaa6684ae1aa6a2eb8f3119f1fdf11334d7'))
    coin = await node_client.get_coin_record_by_name(coin_name)
    sender_puzzle_hash =  await get_sender_puzzle_hash_of_cat_coin(coin, node_client)

    sender_address = encode_puzzle_hash(sender_puzzle_hash, "xch")
    print(f"Sender address: {sender_address}")

    node_client.close()
    await node_client.await_closed()
    
    



if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    try:
     
        loop.run_until_complete(main())

        loop.stop()
     
    except IOError:
        print("File not accessible")
    except Exception as e:
        print(e)

