from ast import Set
import asyncio
import datetime
import os
import json
import time
from typing import List, Optional, Dict
import requests
from logzero import logger
from fastapi.responses import JSONResponse
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.util.bech32m import encode_puzzle_hash
from chia.types.coin_spend import CoinSpend

from ozone_block_scanner.block_scanner import scan_blocks_range
from ozoneapi.cat_data import CatData

import ozoneapi.config as settings
from chia.types.coin_record import CoinRecord
from chia.types.blockchain_format.sized_bytes import bytes32

WAIT_TIME = 20


async def get_full_node_client() -> FullNodeRpcClient:
    config = settings.CHIA_CONFIG
    full_node_client = await FullNodeRpcClient.create(config['self_hostname'], config['full_node']['rpc_port'],
                                                      settings.CHIA_ROOT_PATH, settings.CHIA_CONFIG)
    return full_node_client


def transaction_processed(coin_name: str):
    return os.path.exists(f"./delivers/sent/{coin_name}.json") or os.path.exists(
        f"./delivers/active/{coin_name}.json") or os.path.exists(f"./delivers/fails/{coin_name}.json")


async def get_staking_coins(full_node_client: FullNodeRpcClient, month: int) -> List:
    with open('staking_list.json') as json_file:
        data = json.load(json_file)
        founded: Optional[dict] = None
        for item in data:
            if item['month'] == month:
                founded = item
                break

        if founded is None:
            return JSONResponse(status_code=404, content={'error': 'not found'})

        puzzle_hash = bytes32(bytes.fromhex(founded["cat_ph"]))

        records = await full_node_client.get_coin_records_by_puzzle_hash(puzzle_hash=puzzle_hash,
                                                                         include_spent_coins=True,
                                                                         start_height=1953631)

        result = []
        from ozoneapi.cat_utils import get_sender_puzzle_hash_of_cat_coin
        for item in records:
            coin_record: CoinRecord = item
            if transaction_processed(coin_record.name.hex()):
                # print(f"Coin already sent {coin_record.name.hex()}")
                continue

            puzzle_hash: Optional[bytes32] = await get_sender_puzzle_hash_of_cat_coin(coin_record, full_node_client)

            create_date_time = datetime.datetime.utcfromtimestamp(int(coin_record.timestamp))

            if coin_record.coin.amount < 300000:
                continue
            amount = coin_record.coin.amount / 1000
            inflacion = int(founded["percentage"]) / 365
            diaria = (amount * inflacion) / 100
            dias = 30
            if month == 1:
                dias = 30
            elif month == 3:
                dias = 30 * 3
            elif month == 6:
                dias = 30 * 6
            elif month == 12:
                dias = 365

            months_delta = datetime.timedelta(days=dias)
            payment_date_time = create_date_time + months_delta
            payment_date_time = payment_date_time.replace(hour=0, minute=0, second=0, microsecond=0)

            posible_payment = (dias * diaria) + amount
            coin_json = coin_record.to_json_dict()
            coin_json["name"] = coin_record.coin.name().hex()
            result.append([coin_json, {"withdrawal_puzzle_hash": puzzle_hash.hex(),
                                       "withdrawal_address": encode_puzzle_hash(puzzle_hash, "xch"),
                                       "withdrawal_date_time": payment_date_time.strftime("%Y-%m-%d %H:%M:%S"),
                                       "create_date_time": create_date_time.strftime("%Y-%m-%d %H:%M:%S"),
                                       "amount": float(amount),
                                       "posible_withdrawal": float(posible_payment)}])

        return result


class ChiaSync:
    blockchain_state: Dict = {}
    puzzle_hashes: Dict = {}
    node_rpc_client: Optional[FullNodeRpcClient] = None
    task: Optional[asyncio.Task] = None
    tokens_task: Optional[asyncio.Task] = None
    watch_dog_task: Optional[asyncio.Task] = None
    tokens_list: List[CatData] = []
    last_processed: float = 0
    slow_phs: set[bytes32] = set()
    state = None
    peak_broadcast_callback = None
    staking_data = {}
    catkchi_wallets_data = {}

    @staticmethod
    def start(state):
        ChiaSync.node_rpc_client = state.client
        ChiaSync.state = state
        if ChiaSync.task is not None:
            if not ChiaSync.task.cancelled():
                ChiaSync.task.cancel()
        ChiaSync.task = asyncio.create_task(ChiaSync.load_state_loop())

        if ChiaSync.tokens_task is not None:
            if not ChiaSync.tokens_task.cancelled():
                ChiaSync.tokens_task.cancel()
        ChiaSync.tokens_task = asyncio.create_task(ChiaSync.load_tokens_loop())

    @staticmethod
    def peak() -> int:

        if ChiaSync.blockchain_state is not None:
            if "peak" in ChiaSync.blockchain_state:
                return ChiaSync.blockchain_state["peak"].height
        return 0

    @staticmethod
    async def load_state_loop():
        while True:
            ChiaSync.last_processed = time.time()
            try:
                last_peak = ChiaSync.peak()
                ChiaSync.blockchain_state = await ChiaSync.node_rpc_client.get_blockchain_state()
                print(f"blockchain height: {ChiaSync.peak()}")

                if ChiaSync.peak() > last_peak:
                    if last_peak == 0:
                        last_peak = ChiaSync.peak() - 5
                    asyncio.create_task(ChiaSync.check_staking_coins())
                    asyncio.create_task(ChiaSync.check_catkchi_wallets())
                    if ChiaSync.peak_broadcast_callback is not None:
                        asyncio.create_task(ChiaSync.peak_broadcast_callback(ChiaSync.peak()))

                    # result = await scan_blocks_range(ChiaSync.node_rpc_client, last_peak, ChiaSync.peak())
                    # result_cont = {}
                    # for coin_result in result[0]:
                    #     if coin_result.spend_type not in result_cont:
                    #         result_cont[coin_result.spend_type] = 0
                    #
                    #     result_cont[coin_result.spend_type] += 1
                    #
                    # print(result_cont)

            except Exception as e:
                print(f"exception: {e}")
            await asyncio.sleep(WAIT_TIME)

    @staticmethod
    async def check_staking_coins():
        months = [1, 3, 6, 12]
        for month in months:
            data = await get_staking_coins(ChiaSync.node_rpc_client, month)
            ChiaSync.staking_data[month] = data

    @staticmethod
    async def check_catkchi_wallets():
        with open('catkchi_addresses.json') as json_file:
            data = json.load(json_file)
            for item in data:
                puzzle_hash = bytes32(bytes.fromhex(item["cat_ph"]))
                coins = await ChiaSync.node_rpc_client.get_coin_records_by_puzzle_hash(puzzle_hash, include_spent_coins=False)
                balance = 0
                for c in coins:
                    coin: CoinRecord = c
                    balance += coin.coin.amount
                item['balance'] = balance / 1000

            ChiaSync.catkchi_wallets_data = data

    @staticmethod
    async def load_tokens_loop():
        while True:
            try:
                r = requests.get('https://api.taildatabase.com/enterprise/tails',
                                 headers={'x-api-version': '1', 'accept': 'application/json'})
                if r.status_code == 200:
                    json_data = r.json()
                    t_list = json_data['tails']
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

                            cat_data = CatData(hash=t["hash"], code=t["code"], name=t["name"],
                                               description=t["description"], multiplier=multiplier, category=category,
                                               supply=t["supply"], hashgreen_price=t["hashgreen_price"],
                                               hashgreen_marketcap=t["hashgreen_marketcap"], clvm=clvm,
                                               chialisp=chialisp, logo_url=logo_url,
                                               website_url=t["website_url"], discord_url=t["discord_url"],
                                               twitter_url=t["twitter_url"])
                            token_list.append(cat_data)
                        except Exception as e:
                            print(f"exception: {e}")

                    ChiaSync.tokens_list = token_list

            except Exception as e:
                print(f"exception: {e}")
            await asyncio.sleep(60 * 30)

    @staticmethod
    async def on_found(puzzle_sync_result: List, end_heigth: int, puzzle_hash: bytes32):
        if puzzle_hash in ChiaSync.puzzle_hashes:
            item = ChiaSync.puzzle_hashes[puzzle_hash]
            for socket in item['sockets']:
                await socket.send_text(
                    json.dumps({"coin": puzzle_sync_result, "heigth": end_heigth, "puzzle_hash": puzzle_hash}))

    @staticmethod
    async def send_alert(coin_record: CoinRecord):
        parent_coin: Optional[CoinRecord] = \
            await ChiaSync.node_rpc_client.get_coin_record_by_name(coin_record.coin.parent_coin_info)
        if parent_coin is None:
            logger.debug(f"Without parent coin: {coin_record.coin.parent_coin_info}")
            await ChiaSync.on_found([coin_record.to_json_dict(), None],
                                    int(coin_record.coin.confirmed_block_index), coin_record.coin.puzzle_hash)

        parent_coin_spend: Optional[CoinSpend] = \
            await ChiaSync.node_rpc_client.get_puzzle_and_solution(parent_coin.name, parent_coin.spent_block_index)
        if parent_coin_spend is None:
            logger.debug(f"Without parent coin: {coin_record.coin.parent_coin_info}")
            await ChiaSync.on_found([coin_record.to_json_dict(), None],
                                    int(coin_record.coin.confirmed_block_index), coin_record.coin.puzzle_hash)

        await ChiaSync.on_found([coin_record.to_json_dict(), parent_coin_spend.to_json_dict()],
                                int(coin_record.confirmed_block_index), coin_record.coin.puzzle_hash)

        return True

    @staticmethod
    async def get_staking_data(month: int, state: int):
        if month in ChiaSync.staking_data:

            if ChiaSync.staking_data[month] is not None:
                return ChiaSync.staking_data[month]

        data = await get_staking_coins(ChiaSync.node_rpc_client, month)

        ChiaSync.staking_data[month] = data
        return data

    @staticmethod
    def close():
        if ChiaSync.task is not None:
            ChiaSync.task.cancel()
            ChiaSync.task = None
