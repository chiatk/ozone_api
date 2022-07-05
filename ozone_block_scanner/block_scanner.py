from typing import Optional, List

from chia.consensus.block_record import BlockRecord
from chia.rpc.full_node_rpc_client import FullNodeRpcClient
from chia.types.blockchain_format.program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.util.hash import std_hash
from chia.wallet.did_wallet.did_wallet_puzzles import DID_INNERPUZ_MOD
from chia.wallet.puzzles.cat_loader import CAT_MOD
from pydantic import BaseModel
from enum import Enum

from ozone_block_scanner.did import get_did_info_from_coin_spend
from ozone_block_scanner.nft import get_nft_info_from_coin_spend

MIN_CAT_BLOCK_HEIGHT = 1000000
MIN_NFT_BLOCK_HEIGHT = 1000000
MIN_DID_BLOCK_HEIGHT = 1000000


class CoinSpendType(Enum):
    standard = "xch"
    cat = "cat"
    nft = "nft"
    did = "did"
    unknown = 'unk'


class ScannedBlock(BaseModel):
    coin_record: CoinRecord
    coin_spend: CoinSpend
    inner_puzzle_hash: bytes32
    outer_puzzle_hash: Optional[bytes32]
    sender_inner_puzzle_hash: Optional[bytes32]
    type: CoinSpendType
    mod_hash: bytes32
    coin_name: bytes32
    extra: Optional[list]
    did_id: Optional[bytes32]


async def get_sender_puzzle_hash_of_cat_coin(parent_coin_spend: CoinSpend) -> \
        Optional[tuple[bytes32, bytes32, bytes32]]:
    puzzle_reveal: SerializedProgram = parent_coin_spend.puzzle_reveal
    solution_program = parent_coin_spend.solution.to_program()
    mod, curried_args = puzzle_reveal.uncurry()
    if mod == CAT_MOD:
        arguments = list(curried_args.as_iter())
        puzzle = arguments[2]
        sender_puzzle_hash = puzzle.get_tree_hash()

        arguments = list(solution_program.as_iter())
        receiver_puzzle_hash = list(arguments[0].rest().first().as_iter())[2].rest().first().as_python()
        return sender_puzzle_hash, receiver_puzzle_hash, std_hash(bytes(CAT_MOD))

    return None


async def scan_addition_coin(coin_record: CoinRecord, node_client: FullNodeRpcClient, ):
    # coin_record: Optional[CoinRecord] = None
    coin_spend: Optional[CoinSpend] = None
    inner_puzzle_hash: Optional[bytes32] = None
    sender_inner_puzzle_hash: Optional[bytes32] = None
    outer_puzzle_hash: Optional[bytes32] = None
    mod_hash: Optional[bytes32] = None
    did_id: Optional[bytes32] = None
    extra = [] # can be NftInfo is NFT

    spend_type: CoinSpendType = CoinSpendType.standard
    coin_name: Optional[bytes32] = coin_record.coin.name()

    parent_coin: Optional[CoinRecord] = await node_client.get_coin_record_by_name(coin_record.coin.parent_coin_info)
    parent_coin_spend: Optional[CoinSpend] = await \
        node_client.get_puzzle_and_solution(parent_coin.name, parent_coin.spent_block_index)

    puzzle_reveal: SerializedProgram = parent_coin_spend.puzzle_reveal
    mod, curried_args = puzzle_reveal.uncurry()

    coin_spend = parent_coin_spend
    mod_hash = std_hash(bytes(mod))

    founded = False

    if coin_record.confirmed_block_index >= MIN_CAT_BLOCK_HEIGHT:
        cat_puzzles = await get_sender_puzzle_hash_of_cat_coin(parent_coin_spend)
        if cat_puzzles is not None:
            founded = True

            _sender_inner_puzzle_hash, _inner_puzzle_hash, _mod_hash = cat_puzzles
            inner_puzzle_hash = _inner_puzzle_hash
            sender_inner_puzzle_hash = _sender_inner_puzzle_hash

            outer_puzzle_hash = coin_record.coin.puzzle_hash
            mod_hash = _mod_hash
            spend_type = CoinSpendType.cat
    if coin_record.confirmed_block_index >= MIN_DID_BLOCK_HEIGHT and not founded:
        did_result = get_did_info_from_coin_spend(coin_record.coin, coin_spend)
        if did_result is not None:
            founded = True
            inner_puzzle_hash: bytes32 = did_result["p2_puzzle_hash"]
            outer_puzzle_hash = coin_record.coin.puzzle_hash
            mod_hash = DID_INNERPUZ_MOD.get_tree_hash()
            spend_type = CoinSpendType.did

    if coin_record.confirmed_block_index >= MIN_NFT_BLOCK_HEIGHT and not founded:
        nft_result = get_nft_info_from_coin_spend(coin_spend, coin_record, node_client)
        if nft_result is not None:
            founded = True
            nft_info, new_did_id, new_p2_puzzle_hash, lineage_proof = nft_result
            inner_puzzle_hash = new_p2_puzzle_hash
            outer_puzzle_hash = coin_record.coin.puzzle_hash
            did_id = new_did_id
            extra.append(nft_info)
            spend_type = CoinSpendType.nft

    if not founded:
        inner_puzzle_hash = coin_record.coin.puzzle_hash
        sender_inner_puzzle_hash = parent_coin.coin.puzzle_hash

    return ScannedBlock(**{
        "coin_record": coin_record,
        "coin_spend": coin_spend,
        "inner_puzzle_hash": inner_puzzle_hash,
        "outer_puzzle_hash": outer_puzzle_hash,
        "sender_inner_puzzle_hash": sender_inner_puzzle_hash,
        "type": spend_type,
        "mod_hash": mod_hash,
        "coin_name": coin_record.coin.name(),
        "extra": extra,
        "did_id": did_id
    })


async def puzzle_hash_tracing(node_client: FullNodeRpcClient, start: int = 1, end: int = None) -> \
        tuple[list[ScannedBlock], list[CoinRecord]]:
    """
    El método get_block_recors devuelve el primer bloque pero no el último.
    Ejemplo si pones de 500 a 600 te devuelve hasta 599.
    reward_claims_incorporated es diferente de None, es un bloque de transacción.
    Esta función solo necesita un bloque inicial para iniciar el análisis.
    """

    records: List[BlockRecord] = await node_client.get_block_records(start, end)
    processed_additions: List[ScannedBlock] = []
    removals: List[CoinRecord] = []

    for block_record in records:

        header_hash = bytes32.from_hexstr(block_record.get('header_hash'))

        additions, removals = await node_client.get_additions_and_removals(header_hash)

        for cr in additions:
            coin_record: CoinRecord = cr
            analyzer_result = await scan_addition_coin(coin_record, node_client)

        removals.extend(removals)

    return processed_additions, removals
