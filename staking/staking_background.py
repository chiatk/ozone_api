
from ast import Dict
import asyncio
from typing import Optional
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.types.blockchain_format.coin import Coin
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.consensus.constants import ConsensusConstants
from chia.util.ints import uint8, uint16, uint32, uint64
from chia.util.byte_types import hexstr_to_bytes
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.full_node.signage_point import SignagePoint
from chia.types.end_of_slot_bundle import EndOfSubSlotBundle
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.consensus.pot_iterations import calculate_iterations_quality
from chia.util.lru_cache import LRUCache
from chia.util.chia_logging import initialize_logging
from chia.wallet.transaction_record import TransactionRecord
from chia.pools.pool_puzzles import (
    get_most_recent_singleton_coin_from_coin_spend,
)

loop = asyncio.get_event_loop()
 
class StakingBackground:

    def __init__(self, app_config: Dict,) -> None:
        self.node_rpc_client: Optional[FullNodeRpcClient] = None
        self.node_rpc_port = app_config["node_rpc_port"]
        self.wallet_rpc_client: Optional[WalletRpcClient] = None
        self.wallet_rpc_port = app_config["wallet_rpc_port"]
        self.app_config = app_config
        self.wallet_id = app_config["wallet_id"]
        self.wallet_fingerprint = app_config["wallet_fingerprint"]


    async def start(self, node: FullNodeRpcClient, wallet: WalletRpcClient):
        self.node_rpc_client = node
        self.wallet_rpc_client = wallet
        
        res = await self.wallet_rpc_client.log_in(fingerprint=self.wallet_fingerprint)
        if not res["success"]:
            raise ValueError(f"Error logging in: {res['error']}. Make sure your config fingerprint is correct.")

        state2 = await wallet.get_wallets()

        balance = await self.wallet_rpc_client.get_wallet_balance(self.wallet_id)
        amount = balance /1000
        print(f"Balance: {amount}")

        while(True):
            await asyncio.sleep(5)


