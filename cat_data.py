from typing import Optional
from pydantic import BaseModel


class CatData(BaseModel):
    hash: Optional[str] = None
    code: Optional[str] = None
    name: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    multiplier: Optional[int] = None
    supply: Optional[int] = None
    hashgreen_price: Optional[float] = None
    hashgreen_marketcap: Optional[int] = None
    clvm: Optional[str] = None
    chialisp: Optional[str] = None
    logo_url: Optional[str] = None
    website_url: Optional[str] = None
    discord_url: Optional[str] = None
    twitter_url : Optional[str] = None