from typing import Optional, List, Any

from pydantic import BaseModel, BaseSettings
 

 

class Asset(BaseModel):
    coin_idL: str
    asset_type: str
    asset_id: str
    confirmed_height: int
    spent_height: int
    coin: dict
    lineage_proof: dict
    p2_puzzle_hash: str
    nft_did_id: str
    curried_params: dict

 