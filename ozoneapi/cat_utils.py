import asyncio
import datetime
import json
from lib2to3.pgen2.token import OP
from optparse import Option
import os
from pickletools import uint4
from anyio import Path
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
 
from chia.util.byte_types import hexstr_to_bytes
from chia.types.coin_record import CoinRecord
from chia.types.blockchain_format.sized_bytes import bytes32
from starlette.websockets import WebSocket, WebSocketDisconnect

from chia.full_node.bundle_tools import simple_solution_generator
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions, mempool_check_time_locks
from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
from chia.consensus.cost_calculator import NPCResult
from chia.full_node.mempool import Mempool
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.util.config import load_config

from chia.util.bech32m import encode_puzzle_hash, decode_puzzle_hash 

CHIA_ROOT_PATH = Path(os.environ.get('CHIA_ROOT_PATH'))
CHIA_CONFIG = load_config(DEFAULT_ROOT_PATH, "config.yaml")
 

async def get_full_node_client() -> FullNodeRpcClient:
    config = CHIA_CONFIG
    full_node_client = await FullNodeRpcClient.create(config['self_hostname'], config['full_node']['rpc_port'],
                                                      CHIA_ROOT_PATH, CHIA_CONFIG)
    return full_node_client

  

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

async def get_inner_puzzle_hash_of_coin(coin_record: CoinRecord, node_client: FullNodeRpcClient) -> Optional[bytes32]:
    """
    Get the inner puzzle hash  of the cat coin.
    First obtain the parent coin, then, get the parent coin spend.
    When the coin spend is found, get the puzzle_reveal, uncurry it, get the mod and the arguments
    get the arguments, take the second argument and get the puzzle hash of the sender.

    """ 
    parent_coin: Optional[CoinRecord] = await node_client.get_coin_record_by_name(coin_record.coin.parent_coin_info)
    parent_coin_spend: Optional[CoinSpend] = await node_client.get_puzzle_and_solution(parent_coin.name, parent_coin.spent_block_index)
    value= parent_coin_spend.to_json_dict()
    puzzle_reveal: SerializedProgram = parent_coin_spend.puzzle_reveal
    solution_program =parent_coin_spend.solution.to_program()
    solution = list(solution_program.as_iter())     
    block = await node_client.get_block_record_by_height(parent_coin.spent_block_index)


    mod, curried_args = puzzle_reveal.uncurry()
    if mod == CAT_MOD:
        arguments = list(solution_program.as_iter())
        puzzle_hash= list(arguments[0].rest().first().as_iter())[2].rest().first().as_python()
 
        return puzzle_hash
      
    else:
        print(f"{coin_record.coin.name.hex()} is not a cat coin")
    
    return None

async def main():
    node_client = await get_full_node_client()
    coin_name = bytes32(bytes.fromhex('45b797e4f70164d670a7379624186ca9249e2f9459fd8ad431789836d427d754'))
    coin = await node_client.get_coin_record_by_name(coin_name)
    print(coin.coin.puzzle_hash.hex())
    sender_puzzle_hash =  await get_sender_puzzle_hash_of_cat_coin(coin, node_client)
    

    sender_address = encode_puzzle_hash(sender_puzzle_hash, "xch")
    print(f"Sender address: {sender_address}")

    inner_puzzle_hash =  await get_inner_puzzle_hash_of_coin(coin, node_client)
    print(bytes32(inner_puzzle_hash).hex())

    sender_address = encode_puzzle_hash(inner_puzzle_hash, "xch")
    print(f"Inner address: {sender_address}")

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



def get_spend_bundlecost(spend_bundle: SpendBundle ) -> uint4:
    program = simple_solution_generator(spend_bundle) 
    config = config = CHIA_CONFIG
    overrides = config["network_overrides"]["constants"][config["selected_network"]]
    consensus_constants = DEFAULT_CONSTANTS.replace_str_to_bytes(**overrides)
    result: NPCResult = get_name_puzzle_conditions( program, consensus_constants.MAX_BLOCK_COST_CLVM,\
         cost_per_byte=consensus_constants.COST_PER_BYTE, mempool_mode=True)

    return result.cost 
def min_fee_for_bundle(spend_bundle: SpendBundle  )-> float:
    """
    Get the minimum fee for a bundle.
    """
    bundle_cost = get_spend_bundlecost(spend_bundle)
    config = config = CHIA_CONFIG
    overrides = config["network_overrides"]["constants"][config["selected_network"]]
    consensus_constants = DEFAULT_CONSTANTS.replace_str_to_bytes(**overrides)
    mempool_max_total_cost = int(consensus_constants.MAX_BLOCK_COST_CLVM * consensus_constants.MEMPOOL_BLOCK_BUFFER)
    mempool: Mempool = Mempool(mempool_max_total_cost)
    return mempool.get_min_fee_rate(bundle_cost)

