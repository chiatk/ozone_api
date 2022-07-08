
from ast import Dict, List
import asyncio
import datetime
import json
import math
import shutil
import os
import time
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
import os, shutil, pathlib, fnmatch

from ozone_block_scanner.block_scanner import get_sender_puzzle_hash_of_cat_coin

def move_dir(src_path: str, dst_path: str):
    shutil.move(src_path, dst_path)

CATKCHI_TAIL_HASH:str =  os.getenv('CATKCHI_TAIL_HASH', "aa53978aaac154e32380aaf6322cd316696442248f1d15051007bc48b011694b")

loop = asyncio.get_event_loop()

async def get_staking_coins(full_node_client: FullNodeRpcClient, founded: Optional[dict]) -> List:
          
        puzzle_hash = bytes32(bytes.fromhex(founded["cat_ph"]))
        month = int(founded["month"])
        
        records = await full_node_client.get_coin_records_by_puzzle_hash(puzzle_hash=puzzle_hash,\
                    include_spent_coins=True,   start_height=1953631)

        result = []
        from ozoneapi.cat_utils import get_sender_puzzle_hash_of_cat_coin
        for item in records:
            coin_record: CoinRecord = item
            puzzle_hash:Optional[bytes32] = await get_sender_puzzle_hash_of_cat_coin(coin_record, full_node_client)

            create_date_time = datetime.datetime.utcfromtimestamp(coin_record.timestamp)
          
            if(coin_record.coin.amount<300000):
                continue
            amount = coin_record.coin.amount / 1000
            inflacion = int(founded["percentage"]) / 365
            diaria =(amount * inflacion) /  100
            dias = 30
            horas = 0
            if( month == 1):
                dias = 30
            elif( month == 3):
                dias = 30*3
            elif( month == 6):
                dias = 30*6
            elif( month == 12):
                dias = 365
            elif(month == 0):
                horas = 1
                dias = 0

            monts_delta = datetime.timedelta(days = dias, hours=horas) 
            payment_date_time = create_date_time + monts_delta
            payment_date_time = payment_date_time.replace(hour=0, minute=0, second=0, microsecond=0)
           
            posible_payment =  (dias * diaria) + amount
            coin_json = coin_record
        
            result.append([coin_json, {"withdrawal_puzzle_hash": puzzle_hash,\
                    "withdrawal_address": encode_puzzle_hash(puzzle_hash, "xch"),\
                    "withdrawal_date_time":payment_date_time ,\
                    "create_date_time":create_date_time ,\
                    "amount":float(amount), \
                    "posible_withdrawal":float(posible_payment)}, 
                    {"withdrawal_puzzle_hash": puzzle_hash.hex(),\
                    "withdrawal_address": encode_puzzle_hash(puzzle_hash, "xch"),\
                    "withdrawal_date_time":payment_date_time.strftime("%Y-%m-%d %H:%M:%S"),\
                    "create_date_time":create_date_time.strftime("%Y-%m-%d %H:%M:%S"),\
                    "amount":float(amount), \
                    "posible_withdrawal":float(posible_payment)}])
        
        return result
 
class StakingBackground:

    def __init__(self, app_config: Dict,) -> None:
        self.node_rpc_client: Optional[FullNodeRpcClient] = None
        self.node_rpc_port = app_config["node_rpc_port"]
        self.wallet_rpc_client: Optional[WalletRpcClient] = None
        self.wallet_rpc_port = app_config["wallet_rpc_port"]
        self.app_config = app_config
        self.wallet_id = app_config["wallet_id"]
        self.wallet_fingerprint = app_config["wallet_fingerprint"]
        self.staking_wallets_data  = Optional[Dict]
        self.worker: Optional[asyncio.Task] = None
        self.blockchain_state = {"peak": None}


    async def start(self, node: FullNodeRpcClient, wallet: WalletRpcClient):
        self.node_rpc_client = node
        self.wallet_rpc_client = wallet
        
        res = await self.wallet_rpc_client.log_in(fingerprint=self.wallet_fingerprint)
        if not res["success"]:
            raise ValueError(f"Error logging in: {res['error']}. Make sure your config fingerprint is correct.")

        state2 = await wallet.get_wallets()

        balance = await self.wallet_rpc_client.get_wallet_balance(self.wallet_id)
        amount = balance["spendable_balance"] /1000
        print(f"Balance: {amount}  CTK")

        with open('./staking_list_background.json') as json_file:
            self.staking_wallets_data = json.load(json_file)
        for row in self.staking_wallets_data:
            puzzle_hash = decode_puzzle_hash(row["address"])
            cat_puzzle = bytes32(bytes.fromhex(row["cat_ph"]))
            row["puzzle_hash"] = puzzle_hash.hex()
            row["cat_puzzle_32"] = cat_puzzle
        
        self.worker = asyncio.create_task(self.worker_loop())
        while(True):
            await asyncio.sleep(5)

    async def spendable_balance(self):
        balance = await self.wallet_rpc_client.get_wallet_balance(self.wallet_id)
        amount = balance["spendable_balance"] /1000
        return amount
    async def update_hot_wallet(self, address:str, cat_ph: bytes32, balance: int):
        with open('catkchi_addresses.json', "r", encoding='utf-8') as json_file:
            data = json.load(json_file)
            updated = False
            for item in data:
                if item["type"] =='hot' and item["name"] == "Staking hot wallet":
                    item["address"] = address
                    item["cat_ph"] = cat_ph.hex()
                    item["balance"] = balance
                    updated = True
                    break

            if updated:
                with open("catkchi_addresses.json", "w", encoding='utf-8') as jsonFile:
                    json.dump(data, jsonFile, indent=4,  ensure_ascii=False)
            




    async def calc_hot_wallet(self):
        balance = await self.spendable_balance()
        coins = await self.wallet_rpc_client.select_coins(amount=balance*1000, wallet_id=self.wallet_id)
        coins.sort(key=lambda x: int(x.amount), reverse=False)
        if len(coins)>0:
            biggest = coins[-1]
            coin_record = await self.node_rpc_client.get_coin_record_by_name(biggest.name())
            parent_coin: Optional[CoinRecord] = await self.node_rpc_client.get_coin_record_by_name(biggest.parent_coin_info)
            parent_coin_spend: Optional[CoinSpend] = None
            if parent_coin is not None:
                parent_coin_spend = await \
                    self.node_rpc_client.get_puzzle_and_solution(parent_coin.coin.name(), parent_coin.spent_block_index)
                cat_puzzles = await get_sender_puzzle_hash_of_cat_coin(parent_coin_spend, coin_record)
                if cat_puzzles is not None:
                  
                    _sender_inner_puzzle_hash, _, _mod_hash = cat_puzzles
                    #address = encode_puzzle_hash(bytes32(_inner_puzzle_hash), "xch")
                    address2 = encode_puzzle_hash(bytes32(_sender_inner_puzzle_hash), "xch")
                    await self.update_hot_wallet(address2, biggest.puzzle_hash, int(biggest.amount)/1000)

        print(coins)
    
    async def worker_loop(self):
        while(True):
            try:
                await self.calc_hot_wallet()
                wallet_synced = await self.wallet_rpc_client.get_synced()
                if not wallet_synced:
                    print(f"Wallet not sync, waiting")
                    await asyncio.sleep(60)
                    continue
                print("executing worker")
                await self.worker_fn()
            except Exception as e:
                print(f"exception: {e}")
            now  = datetime.datetime.utcfromtimestamp(time.time())
            if now.hour>3:
                print("sleep 1 hour....")
                await asyncio.sleep(60*60)
            await asyncio.sleep(10)



    def get_confirmation_security_threshold(self):
        return 8
    
    async def worker_fn(self):

        arr = os.listdir("./delivers/active")
        if(len(arr) >0):
            print("Waiting ")
            #TODO, Es necesario darle seguimiento a la transaccion, cuando esta finalice, mover el archivo de active a sended
            # de esta forma , se podra iniciar otra transaccion si es necsario.
            file = f"./delivers/active/{ arr[0]}"
            with open(file) as json_file:
                active_transaction = json.load(json_file)
                
            transaction_name: Optional[bytes32] =  bytes32(hexstr_to_bytes(active_transaction["trxn_id"]))
            transaction: Optional[TransactionRecord] = None
            transaction_confirmed = False
            peak_height = 0
            coin_name : Optional[str] = active_transaction["coin"]

            while (
                not transaction_confirmed
                or not (peak_height - transaction.confirmed_at_height) > self.get_confirmation_security_threshold() ):
                try:
                    transaction = await self.wallet_rpc_client.get_transaction(self.wallet_id, transaction_name)
                    transaction_confirmed = transaction.confirmed
                except Exception as e:
                    print(f"Error getting transaction: {e}")
                
                self.blockchain_state = await self.node_rpc_client.get_blockchain_state()
                peak_height = self.blockchain_state["peak"].height
                confirmations = 0
                if transaction.confirmed_at_height > 0:
                    confirmations = peak_height - transaction.confirmed_at_height
 
                print(
                f"Waiting for transaction to obtain {self.get_confirmation_security_threshold()} "
                f"({self.get_confirmation_security_threshold() + transaction.confirmed_at_height})"
                f"confirmations = {confirmations}"  )

                if not transaction.confirmed:
                    print(f"Not confirmed. In mempool? {transaction.is_in_mempool()}")
                
                    await  asyncio.sleep(10)
                else:
                    print(f"Confirmations: {confirmations}")
                    if not ((peak_height - transaction.confirmed_at_height) > self.get_confirmation_security_threshold()) :
                        await  asyncio.sleep(10)
        
            if(transaction_confirmed):
               await self.move_file_to_sent(coin_name)
               await self.calc_hot_wallet()

              

            
        else:
            now  = datetime.datetime.utcfromtimestamp(time.time())

            for item in self.staking_wallets_data:   
                # if item["month"] > 0:
                #     continue 
                print(f"Checking month {item['month']}")

                items = await get_staking_coins(self.node_rpc_client, item)

                for wallet_data in items:
                    #diff = now - wallet_data[1]["withdrawal_date_time"]
                    coin_record = wallet_data[0]
                    coin_name = coin_record.coin.name()
                    #TODO, tambien es necesario revisar si la transaccion ya fue envida, simplemente se revisa la carpeta sended para ello.
                    if not self.transaction_processed(coin_name.hex()):
                        if(now >= wallet_data[1]["withdrawal_date_time"]):
                            amount = wallet_data[1]["posible_withdrawal"]
                            spendable_balance = await self.spendable_balance()
                            if spendable_balance>= amount and amount >= 300.0:
                                print(coin_name)
                                await self.create_active_file(coin_name.hex(),"0xff" )
                                try:
                                    await self.execute_transaction(wallet_data)
                                    return
                                except Exception as e:
                                    print(f"exception: {e}")
                                    self.delete_active_file(coin_name.hex())
                                    continue
                            else:
                                print(f"Spendable balance {spendable_balance} and amount =  {amount} not sufficient")

    async def execute_transaction(self, data: List):
        coin_record = data[0]
        coin_name = coin_record.coin.name()
        amount = data[1]["posible_withdrawal"]
        address = data[1]["withdrawal_address"]

        self.blockchain_state = await self.node_rpc_client.get_blockchain_state()
        wallet_synced = await self.wallet_rpc_client.get_synced()
        ctk_wallet: Optional[dict] = None
        if(wallet_synced):
            wallets = await self.wallet_rpc_client.get_wallets()
            
            ctk_hash = CATKCHI_TAIL_HASH
            for w in wallets:
                try:
                    wallet: dict = w
                    tailhash = await self.wallet_rpc_client.get_cat_asset_id(wallet["id"])
                    if tailhash is not None and tailhash != "":
                        tailhash_str = bytes32(tailhash).hex()
                        if tailhash_str  == ctk_hash:
                            ctk_wallet = wallet
                            break
                except Exception as e:
                    #self.log.error(e)
                    pass
                    
        
        if ctk_wallet is None:
            self.log.error("Could not find ctk wallet") 
            raise Exception("Not found")
        transaction: TransactionRecord = await self.wallet_rpc_client.cat_spend(
                             wallet_id=ctk_wallet["id"], amount= uint64(int(amount*1000)), inner_address= address, fee = uint64(0) )
        coins_map_list = []
        for coin in transaction.additions:
            coin_map = coin.to_json_dict()
            coin_map["id"] = coin.name().hex()
            coins_map_list.append(coin_map)
            
        coins_map = {"coins": coins_map_list }
        coins_map.update(data[2])
        await self.create_active_file(coin_name.hex(),transaction.name.hex(), extra=coins_map)


    async def create_active_file(self, coin_name: str, transaction_id: str, extra: Optional[Dict]=None):
        json_data = {"coin":coin_name,"trxn_id": transaction_id}
        if extra is not None:
            json_data.update(extra)
        with open(f"./delivers/active/{coin_name}.json", "w") as outfile:
            json.dump(json_data, outfile, indent=4)

    async def delete_active_file(self, coin_name:str):
        move_dir(f"./delivers/active/{coin_name}.json", f"./delivers/fails/{coin_name}.json")
         

    async def move_file_to_sent(self, coin_name: str):
        move_dir(f"./delivers/active/{coin_name}.json", f"./delivers/sent/{coin_name}.json")
    
    def transaction_processed(self, coin_name: str):
        return os.path.exists(f"./delivers/sent/{coin_name}.json") or os.path.exists(f"./delivers/active/{coin_name}.json") or os.path.exists(f"./delivers/fails/{coin_name}.json")


