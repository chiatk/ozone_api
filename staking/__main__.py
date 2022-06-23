from ast import Dict
import asyncio
import os
from anyio import Path

from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.rpc.wallet_rpc_client import WalletRpcClient
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_ROOT_PATH
from chia.consensus.constants import ConsensusConstants
from chia.consensus.default_constants import DEFAULT_CONSTANTS
import yaml

from staking.staking_background import StakingBackground


loop = asyncio.get_event_loop()

pool_config_path = os.environ.get("STAKING_CATKCHI_CONFIG", os.path.dirname(__file__) + "/../config.yaml")
with open(pool_config_path) as f:
    app_config: Dict = yaml.safe_load(f)
    

CHIA_ROOT_PATH = Path(app_config["wallet_root_config"])
config = load_config(CHIA_ROOT_PATH, "config.yaml")
overrides = config["network_overrides"]["constants"][config["selected_network"]]
constants: ConsensusConstants = DEFAULT_CONSTANTS.replace_str_to_bytes(**overrides)


CHIA_ROOT_PATH = DEFAULT_ROOT_PATH
CHIA_CONFIG = load_config(CHIA_ROOT_PATH, "config.yaml")


async def get_full_node_client() -> FullNodeRpcClient:
    full_node_client = await FullNodeRpcClient.create(CHIA_CONFIG['self_hostname'],
                                                      CHIA_CONFIG['full_node']['rpc_port'],
                                                      CHIA_ROOT_PATH, CHIA_CONFIG)
    return full_node_client


async def get_wallet_client() -> WalletRpcClient:
    wallet_client = await WalletRpcClient.create("localhost", app_config['wallet_rpc_port'],
                                                 CHIA_ROOT_PATH, CHIA_CONFIG)
    return wallet_client



async def main():
    
    i = 0
    while True:
        try:
            i += 1
            staking_manager = StakingBackground(app_config)

            node = await get_full_node_client()
            wallet = await get_wallet_client()
            
            await staking_manager.start(node, wallet)  

        except Exception as e:
            print(e)
            print(f"Waiting for full node to connect (attempt {i})")
            await asyncio.sleep(1)
            continue 


# Press the green button in the gutter to run the script.
if __name__ == '__main__':
    loop.run_until_complete(main())

    loop.stop()
   # db.close()
