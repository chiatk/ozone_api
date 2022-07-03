import datetime
import os
import json
from typing import List, Optional, Dict, Tuple
import aioredis
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
  
  
from chia.util.byte_types import hexstr_to_bytes
from chia.types.coin_record import CoinRecord
from chia.types.blockchain_format.sized_bytes import bytes32
from ozoneapi.cat_data import CatData 
from ozoneapi.chia_sync import ChiaSync
from ozoneapi import config as settings, web_socket 
from ozoneapi.coins_sync import get_full_coin_by_name
 
import traceback
from dateutil.relativedelta import relativedelta

caches.set_config(settings.CACHE_CONFIG)
 
app = FastAPI()

 

cwd = os.path.dirname(__file__)

log_dir = os.path.join(cwd, "logs")

if not os.path.exists(log_dir):
    os.mkdir(log_dir)

logzero.logfile(os.path.join(log_dir, "api.log"))
LOCAL_REDIS_URL = "redis://127.0.0.1:6379"


async def get_full_node_client() -> FullNodeRpcClient:
    config = settings.CHIA_CONFIG
    full_node_client = await FullNodeRpcClient.create(config['self_hostname'], config['full_node']['rpc_port'],
                                                      settings.CHIA_ROOT_PATH, settings.CHIA_CONFIG)
    return full_node_client


@app.on_event("startup")
async def startup():
    app.state.client = await get_full_node_client()
   
    await app.state.client.get_blockchain_state()
    app.state.redis = aioredis.from_url(os.environ.get("REDIS_URL", LOCAL_REDIS_URL), encoding="utf8", decode_responses=True)
    ChiaSync.start(app.state)


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
   
    return data


@router.get("/tokens", response_model=List[CatData])
@cached(ttl=10, key_builder=lambda *args, **kwargs: f"get_tokens: ", alias='default')
async def get_tokens(  request: Request):
    
    return ChiaSync.tokens_list

# @router.post("/get_cat_coins_by_outer_puzzle_hashes", response_model=dict)
# @cached(ttl=10, key_builder=lambda *args, **kwargs: f"get_cat_coins_by_outer_puzzle_hashes:{kwargs['item']}", alias='default')
# async def get_utxos(  request: Request, item=Body({}),):
#     # todo: use blocke indexer and supoort unconfirmed param
#     blockchain_peak = ChiaSync.peak()
#     start_height: Optional[int] = 0
#     sync_heigth = 1000
   
#     include_spent_coins = True

#     if 'start_height' in item:
#         start_height = int(item['start_height'])
 
     
#     if start_height < 1000000:
#         sync_heigth = 200000
#     low_heigth= blockchain_peak

    
    
#     logger.debug(f"start_height: {start_height}  include_spent_coins: {include_spent_coins}")
#     logger.debug(f"item len: {len(item['puzzle_hashes'])}") 

#     puzzle_hashes:List[Tuple[bytes32, int]] = []
#     for puzzle_hash_hex in item['puzzle_hashes']:
#         touple_item :Tuple[bytes32, int] = (bytes32(bytes.fromhex(puzzle_hash_hex[0])), int(puzzle_hash_hex[1]))
#         puzzle_hashes.append(touple_item)

#     full_node_client:FullNodeRpcClient = request.app.state.client
#     coin_records:List[CoinRecord] = []
#     for puzzle_hash_item in puzzle_hashes:
#         try:
#             puzzle_hash, start_height = puzzle_hash_item
#             if start_height == 0:
#                 start_height = 32
#             end_height: Optional[int] = ChiaSync.peak()
#             if end_height - start_height > sync_heigth:
#                 end_height = start_height + sync_heigth
        
#             if end_height< low_heigth:
#                 low_heigth = end_height
           
#             records = await full_node_client.get_coin_records_by_puzzle_hash(puzzle_hash=puzzle_hash,\
#             include_spent_coins=include_spent_coins,   start_height=start_height-32, end_height=end_height)
#             for r in records:
#                 coin_records.append(r)
           
#         except Exception as e:
#             logger.exception(e)
#             print(e)
#             print(f"puzzle_hash: {puzzle_hash_item}")
#             continue
#     coin_records.sort(key=lambda x: int(x.confirmed_block_index), reverse=False)
#     if len(coin_records) > 100:
#         coin_records = coin_records[:100]
#         end_height = int(coin_records[-1].confirmed_block_index)
#         if end_height < low_heigth:
#             low_heigth = end_height
    
#     result = []

#     for row in coin_records:
#         try:
#             if row is None:
#                 print(f"row is None")
#                 continue
#             if row.spent and include_spent_coins == False:
#                  continue
           
#             else:
                
#                 parent_coin: Optional[CoinRecord] = await full_node_client.get_coin_record_by_name(row.coin.parent_coin_info)
#                 if parent_coin is None:
#                     print(f"Without parent coin: {row.coin.parent_coin_info}")
#                     result.append([row.to_json_dict(), None]) 
#                     continue
#                 parent_coin_spend: Optional[CoinSpend] = await full_node_client.get_puzzle_and_solution(parent_coin.name, parent_coin.spent_block_index)
#                 if parent_coin_spend is None:
#                     print(f"Without parent coin spend: {row.coin.parent_coin_info}")
#                     result.append([row.to_json_dict(), None]) 
#                     continue
#                 result.append([row.to_json_dict(), parent_coin_spend.to_json_dict()])      

#         except Exception as e:
#             logger.exception(e)
#             print(row)
#             print(e)
#             print(traceback.format_exc())
           
#             continue 
  
#     return {"coins":result, "end_height": low_heigth, "blockchain_peak": blockchain_peak} 


@router.post("/get_coins_for_puzzle_hashes", response_model=dict)
@cached(ttl=10, key_builder=lambda *args, **kwargs: f"get_coins_for_puzzle_hashes:{kwargs['item']}", alias='default')
async def get_utxos(  request: Request, item=Body({}),):
    # todo: use blocke indexer and supoort unconfirmed param
    blockchain_peak = ChiaSync.peak()
    start_height: Optional[int] = 0
   
    wallet_results = []
 
    logger.debug(f"item len: {len(item['puzzle_hashes'])}") 

    puzzle_hashes:List[Tuple[bytes32, int]] = []
    for puzzle_hash_hex in item['puzzle_hashes']:
        touple_item :Tuple[bytes32, int] = (bytes32(bytes.fromhex(puzzle_hash_hex[0])), int(puzzle_hash_hex[1]))
        puzzle_hashes.append(touple_item)

    full_node_client:FullNodeRpcClient = request.app.state.client
    coin_records:List[CoinRecord] = []
    for puzzle_hash_item in puzzle_hashes:
        try:
            puzzle_hash, start_height = puzzle_hash_item
            sync_heigth = 500000
   
            include_spent_coins = True

            if 'start_height' in item:
                start_height = int(item['start_height'])
        
            
            if start_height < 1000000:
                sync_heigth = 1000000
            
            if puzzle_hash in ChiaSync.slow_phs: 
                sync_heigth = 10000

            logger.debug(f"sync_heigth: {sync_heigth}")


            end_height: Optional[int] = ChiaSync.peak()
            if end_height - start_height > sync_heigth:
                end_height = start_height + sync_heigth
            
            if(end_height > ChiaSync.peak()):
                end_height = ChiaSync.peak()

      
           
            records = await full_node_client.get_coin_records_by_puzzle_hash(puzzle_hash=puzzle_hash,\
            include_spent_coins=include_spent_coins,   start_height=start_height, end_height=end_height)
            if len(records) >100:
                if puzzle_hash is not  ChiaSync.slow_phs: 
                    print(f"puzzle_hash: {puzzle_hash_item} to slow")
                    ChiaSync.slow_phs.add(puzzle_hash)
             
            
            all_addded = True
            for r in records:
                if( len(coin_records)>100):
                    all_addded = False
                    wallet_results.append({"puzzle_hash": puzzle_hash.hex(), "end_height": r.confirmed_block_index})
                    break
                coin_records.append(r)

            if all_addded:
                wallet_results.append({"puzzle_hash": puzzle_hash.hex(), "end_height": end_height})
           
        except Exception as e:
            logger.exception(e)
            print(e)
            print(f"puzzle_hash: {puzzle_hash_item}")
            continue

    coin_records.sort(key=lambda x: int(x.confirmed_block_index), reverse=False)
  


    result = []

    for row in coin_records:
        try:
            if row is None:
                print(f"row is None")
                continue
            if row.spent and include_spent_coins == False:
                 continue
           
            else:
                
                parent_coin: Optional[CoinRecord] = await full_node_client.get_coin_record_by_name(row.coin.parent_coin_info)
                if parent_coin is None:
                    print(f"Without parent coin: {row.coin.parent_coin_info}")
                    result.append([row.to_json_dict(), None]) 
                    continue
                parent_coin_spend: Optional[CoinSpend] = await full_node_client.get_puzzle_and_solution(parent_coin.name, parent_coin.spent_block_index)
                if parent_coin_spend is None:
                    print(f"Without parent coin spend: {row.coin.parent_coin_info}")
                    result.append([row.to_json_dict(), None]) 
                    continue
                result.append([row.to_json_dict(), parent_coin_spend.to_json_dict()])      

        except Exception as e:
            logger.exception(e)
            print(row)
            print(e)
            print(traceback.format_exc())
           
            continue 
  
    return {"coins":result, "wallet_results": wallet_results, "blockchain_peak": blockchain_peak} 



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
            if records is None:
                logger.debug(f"not Found coin: {name}")
                
                continue
            result.append(records.to_json_dict())
           
        except Exception as e:
            logger.exception(e)
            print(traceback.format_exc())
            print(e)
            print(f"puzzle_hash: {name}")
            continue
     
    return {"coins":result } 


@router.post("/get_full_coin_by_names", response_model=dict)
#@cached(ttl=10, key_builder=lambda *args, **kwargs: f"get_cat_coins_by_outer_puzzle_hashes:{kwargs['item']}", alias='default')
async def get_full_coin_by_name_api(  request: Request, item=Body({}),):
    # todo: use blocke indexer and supoort unconfirmed param
  
    names:List[bytes32] = []
    for puzzle_hash_hex in item['coins']:
        coin_name  = bytes32(bytes.fromhex(puzzle_hash_hex))
        names.append(coin_name)

    full_node_client = request.app.state.client
    result = []
    for name in names:
        try:
             
             
            records = await get_full_coin_by_name(name, full_node_client)
            result.append(records)
           
        except Exception as e:
            logger.exception(e)
            print(traceback.format_exc())
            print(e)
            print(f"puzzle_hash: {name}")
            continue
     
    return {"coins":result } 


@router.post("/get_full_nft_coin_by_names", response_model=dict)
#@cached(ttl=10, key_builder=lambda *args, **kwargs: f"get_cat_coins_by_outer_puzzle_hashes:{kwargs['item']}", alias='default')
async def get_full_coin_by_name_api(  request: Request, item=Body({}),):
    # todo: use blocke indexer and supoort unconfirmed param
  
    names:List[bytes32] = []
    for nft_name in item['names']:
        coin_name  =  decode_puzzle_hash(nft_name)
        names.append(coin_name)

    full_node_client = request.app.state.client
    result = []
    for name in names:
        try:
             
             
            records = await get_full_coin_by_name(name, full_node_client)
            result.append(records)
           
        except Exception as e:
            logger.exception(e)
            print(traceback.format_exc())
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
        map = {"error": str(e)}
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


@router.get('/active_versions')
@cached(ttl=10, key_builder=lambda *args, **kwargs: f"active_versions:", alias='default')
async def query_balance( request: Request):
    return {"android":{"min":40, "actual":40}, "ios":{"min":40, "actual":41}}
    

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

@router.get('/staking/list')
async def list_tokens():
    with open('staking_list.json') as json_file:
        data = json.load(json_file)
        for row in data:
            puzzle_hash = decode_puzzle_hash(row["address"])
            cat_puzzle = bytes32(bytes.fromhex(row["cat_ph"]))
            row["puzzle_hash"] = puzzle_hash.hex()
            del row["cat_ph"]
            

        return data
     
@router.get('/staking/{month}/{status}')
async def list_tokens(month: int, status:str, request: Request):
    include_spent_coins = True

    return await ChiaSync.get_staking_data(month, status)
        
        

app.include_router(router, prefix="/v1.1")
app.include_router(web_socket.router, tags=["WebSocket"])