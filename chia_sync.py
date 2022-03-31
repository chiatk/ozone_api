import asyncio
from lib2to3.pgen2.token import OP
import os
import json
from typing import List, Optional, Dict
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
from chia.consensus.block_record import BlockRecord
import config as settings
from chia.util.byte_types import hexstr_to_bytes
from chia.types.coin_record import CoinRecord
from chia.types.blockchain_format.sized_bytes import bytes32


class ChiaSync:
    blockchain_state: Dict = {}
    node_rpc_client: Optional[FullNodeRpcClient] = None
    task :Optional[asyncio.Task] = None


    def start(node: FullNodeRpcClient):
        ChiaSync.node_rpc_client = node
        ChiaSync.task = asyncio.create_task(ChiaSync.load_state_loop())

    def peak()-> BlockRecord:
        return ChiaSync.blockchain_state["peak"].height   

    async def load_state_loop():
        while(True):
            try:
                ChiaSync.blockchain_state = await ChiaSync.node_rpc_client.get_blockchain_state()
                print(f"blockchain height: { ChiaSync.peak() }")
            except Exception as e:
                print(f"exception: {e}")
            await asyncio.sleep(10)
    def close():
        if ChiaSync.task is not None:
            ChiaSync.task.cancel()
            ChiaSync.task = None
    