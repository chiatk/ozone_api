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

caches.set_config(settings.CACHE_CONFIG)

app = FastAPI()

cwd = os.path.dirname(__file__)

log_dir = os.path.join(cwd, "logs")

if not os.path.exists(log_dir):
    os.mkdir(log_dir)

logzero.logfile(os.path.join(log_dir, "api.log"))


async def get_full_node_client() -> FullNodeRpcClient:
    config = settings.CHIA_CONFIG
    full_node_client = await FullNodeRpcClient.create(config['self_hostname'], config['full_node']['rpc_port'],
                                                      settings.CHIA_ROOT_PATH, settings.CHIA_CONFIG)
    return full_node_client


@app.on_event("startup")
async def startup():
    app.state.client = await get_full_node_client()
   
    await app.state.client.get_blockchain_state()

    ChiaSync.start(app.state.client)


@app.on_event("shutdown")
async def shutdown():
    app.state.client.close()
    await app.state.client.await_closed()


def to_hex(data: bytes):
    return data.hex()


def decode_puzzle_hash(address):
    try:
        return inner_decode_puzzle_hash(address)
    except ValueError:
        raise HTTPException(400, "Invalid Address")


def coin_to_json(coin):
    return {
        'parent_coin_info': to_hex(coin.parent_coin_info),
        'puzzle_hash': to_hex(coin.puzzle_hash),
        'amount': str(coin.amount)
    }

router = APIRouter()


class UTXO(BaseModel):
    parent_coin_info: str
    puzzle_hash: str
    amount: str


@router.get("/utxos", response_model=List[UTXO])
@cached(ttl=10, key_builder=lambda *args, **kwargs: f"utxos:{kwargs['address']}", alias='default')
async def get_utxos(address: str, request: Request):
    # todo: use blocke indexer and supoort unconfirmed param
    pzh = decode_puzzle_hash(address)
    full_node_client = request.app.state.client
    coin_records:List[CoinRecord] = await full_node_client.get_coin_records_by_puzzle_hash(puzzle_hash=pzh, include_spent_coins=False)
    data = []

    for row in coin_records:
        if row.spent:
            continue
        data.append(coin_to_json(row.coin))
    print(data)
    return data


@router.get("/tokens", response_model=List[CatData])
@cached(ttl=10, key_builder=lambda *args, **kwargs: f"get_tokens: ", alias='default')
async def get_tokens(  request: Request):
    
    return ChiaSync.tokens_list

@router.post("/get_cat_coins_by_outer_puzzle_hashes", response_model=dict)
@cached(ttl=10, key_builder=lambda *args, **kwargs: f"get_cat_coins_by_outer_puzzle_hashes:{kwargs['item']}", alias='default')
async def get_utxos(  request: Request, item=Body({}),):
    # todo: use blocke indexer and supoort unconfirmed param

    start_height: Optional[int] = None
    end_height: Optional[int] = ChiaSync.peak()
    include_spent_coins = False

    if 'start_height' in item:
        start_height = int(item['start_height'])
    
    if 'end_height' in item:
        end_height = int(item['end_height'])
    
    if 'include_spent_coins' in item:
        include_spent_coins = bool(item['include_spent_coins'])


    puzzle_hashes:List[Tuple[bytes32, int]] = []
    for puzzle_hash_hex in item['puzzle_hashes']:
        touple_item :Tuple[bytes32, int] = (bytes32(bytes.fromhex(puzzle_hash_hex[0])), int(puzzle_hash_hex[1]))
        puzzle_hashes.append(touple_item)

    full_node_client = request.app.state.client
    coin_records:List[CoinRecord] = []
    for puzzle_hash_item in puzzle_hashes:
        try:
            puzzle_hash, start_height = puzzle_hash_item
            if start_height == 0:
                start_height = 32
            #start_height = 32
            records = await full_node_client.get_coin_records_by_puzzle_hash(puzzle_hash=puzzle_hash,\
            include_spent_coins=include_spent_coins,   start_height=start_height-32)
            for r in records:
                coin_records.append(r)
           
        except Exception as e:

            print(e)
            print(f"puzzle_hash: {puzzle_hash_item}")
            continue
    
    result = []

    for row in coin_records:
        try:
            if row.spent and include_spent_coins == False:
                continue
            else:
                parent_coin: Optional[CoinRecord] = await full_node_client.get_coin_record_by_name(row.coin.parent_coin_info)
                if parent_coin is None:
                    result.append([row.to_json_dict(), None]) 
                    continue
                parent_coin_spend: Optional[CoinSpend] = await full_node_client.get_puzzle_and_solution(parent_coin.name, parent_coin.spent_block_index)
                result.append([row.to_json_dict(), parent_coin_spend.to_json_dict()])      

        except Exception as e:

            print(e)
            print(f"puzzle_hash: {puzzle_hash_item}")
            continue 
    print(f"coins size: {len(coin_records)}")
    return {"coins":result, "end_height": end_height} 



@router.post("/get_coin_state", response_model=dict)
#@cached(ttl=10, key_builder=lambda *args, **kwargs: f"get_cat_coins_by_outer_puzzle_hashes:{kwargs['item']}", alias='default')
async def get_utxos(  request: Request, item=Body({}),):
    # todo: use blocke indexer and supoort unconfirmed param
 
  

    names:List[bytes32] = []
    for puzzle_hash_hex in item['coins']:
        coin_name  = bytes32(bytes.fromhex(puzzle_hash_hex))
        names.append(coin_name)

    full_node_client = request.app.state.client
    result = []
    for name in names:
        try:
             
             
            records = await full_node_client.get_coin_record_by_name(coin_id=name )
            result.append(records.to_json_dict())
           
        except Exception as e:

            print(e)
            print(f"puzzle_hash: {name}")
            continue
     
    return {"coins":result } 




@router.post("/sendtx")
async def create_transaction(request: Request, item=Body({})):
    print(item)
    spb = SpendBundle.from_json_dict(item['spend_bundle'])
    full_node_client = request.app.state.client

    try:
        resp = await full_node_client.push_tx(spb)
    except ValueError as e:
        logger.warning("sendtx: %s, error: %r", spb, e)
        raise HTTPException(400, str(e))

    return {
        'status': resp['status'],
        'id': spb.name().hex()
    }


class ChiaRpcParams(BaseModel):
    method: str
    params: Optional[Dict] = None


@router.post('/chia_rpc')
async def full_node_rpc(request: Request, item: ChiaRpcParams):
    # todo: limit method and add cache
    full_node_client = request.app.state.client
    async with full_node_client.session.post(full_node_client.url + item.method, json=item.params,
                                             ssl_context=full_node_client.ssl_context) as response:
        res_json = await response.json()
        return res_json


async def get_user_balance(puzzle_hash: bytes, request: Request):
    full_node_client = request.app.state.client
    coin_records = await full_node_client.get_coin_records_by_puzzle_hash(puzzle_hash=puzzle_hash,
                                                                          include_spent_coins=True)
    amount = sum([c.coin.amount for c in coin_records if c.spent == 0])
    return amount


@router.get('/balance')
@cached(ttl=10, key_builder=lambda *args, **kwargs: f"balance:{kwargs['puzzle_hash']}", alias='default')
async def query_balance(puzzle_hash, request: Request):
    # todo: use blocke indexer and supoort unconfirmed param
    puzzle_hash = bytes32(hexstr_to_bytes(puzzle_hash))
    amount = await get_user_balance(puzzle_hash, request)
    data = {
        'amount': amount
    }
    print(data)
    return data

@router.post('/get_coins_by_names')
@cached(ttl=10, key_builder=lambda *args, **kwargs: f"balance: ", alias='default')
async def get_coins(request: Request, item=Body({})):
    # todo: use blocke indexer and supoort unconfirmed param
    full_node_client = request.app.state.client
    names: List[bytes32] = []
    for name_hex in item['names']:
        names.append(bytes32(bytes.fromhex(name_hex)))
    coin_records:List[CoinRecord] = await full_node_client. \
        get_coin_records_by_names(names=names)
    result = []
    for row in coin_records:
            result.append(row.to_json_dict())

    data = {
        'coin_records': result
    }
 
    return data


class ChiaBlockchainInfo(BaseModel):
    blockchain: str


@router.post("/blockchain")
def blockchain_info(request: Request, item: ChiaBlockchainInfo):
    if item.blockchain != 'xch':
        return JSONResponse(status_code=400, content={'error': 'invalid blockchain'})
    return {"blockchain": {
        "name": "Chia",
        "unit": "Mojo",
        "logo": "/icons/blockchains/chia.png",
        "agg_sig_me_extra_data": "ccd5bb71183532bff220ba46c268991a3ff07eb358e8255a65c30a2dce0e5fbb",
        "ticker": "xch",
        "precision": 12,
        "blockchain_fee": 0
    }}


DEFAULT_TOKEN_LIST = [
    {
        'chain': 'xch',
        'id': 'xch',
        'name': 'XCH',
        'symbol': 'XCH',
        'decimals': 12,
        'logo_url': 'https://static.goby.app/image/token/xch/XCH_32.png',
        'is_verified': True,
        'is_core': True,
    },
    {
        'chain': 'xch',
        'id': '8ebf855de6eb146db5602f0456d2f0cbe750d57f821b6f91a8592ee9f1d4cf31',
        'name': 'Marmot',
        'symbol': 'MRMT',
        'decimals': 3,
        'logo_url': 'https://static.goby.app/image/token/mrmt/MRMT_32.png',
        'is_verified': True,
        'is_core': True,
    },
    {
        'chain': 'xch',
        'id': '78ad32a8c9ea70f27d73e9306fc467bab2a6b15b30289791e37ab6e8612212b1',
        'name': 'Spacebucks',
        'symbol': 'SBX',
        'decimals': 3,
        'logo_url': 'https://static.goby.app/image/token/sbx/SBX_32.png',
        'is_verified': True,
        'is_core': True,
    },
    {
        "chain": "xch",
        "id": "a2cadb541cb01c67c3bcddc73ecf33c8ffa37b0d013688904b2747cede020477",
        "name": "CryptoShibe Gold",
        "symbol": "CSH",
        "decimals": 3,
        "logo_url": "https://static.goby.app/image/token/csh/CSH_32.png",
        "is_core": True
    },
]


@router.get('/tokens')
async def list_tokens():
    return DEFAULT_TOKEN_LIST


app.include_router(router, prefix="/v1")
