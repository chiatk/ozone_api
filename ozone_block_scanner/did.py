import json
import asyncio
from aiocache import caches
from typing import Dict, Optional

from chia.clvm.singleton import SINGLETON_TOP_LAYER_MOD, SINGLETON_LAUNCHER
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.coin_record import CoinRecord
from chia.types.coin_spend import CoinSpend
from chia.wallet.did_wallet.did_wallet_puzzles import DID_INNERPUZ_MOD
from chia.wallet.lineage_proof import LineageProof

SINGLETON_TOP_LAYER_MOD_HASH = SINGLETON_TOP_LAYER_MOD.get_tree_hash()
SINGLETON_LAUNCHER_MOD_HASH = SINGLETON_LAUNCHER.get_tree_hash()


def match_did_puzzle(puzzle: Program):
    try:
        mod, curried_args = puzzle.uncurry()
        if mod == SINGLETON_TOP_LAYER_MOD:
            mod, curried_args = curried_args.rest().first().uncurry()
            if mod == DID_INNERPUZ_MOD:
                return True, curried_args.as_iter()
    except Exception:
        return False, iter(())
    return False, iter(())


def get_did_inner_puzzle_hash(address: bytes, recovery_list_hash: bytes, num_verification: int, singleton_struct,
                              metadata):
    return DID_INNERPUZ_MOD.curry(address, recovery_list_hash, num_verification, singleton_struct,
                                  metadata).get_tree_hash(address)


def to_full_pzh(inner_puzzle_hash: bytes, launcher_id: bytes):
    singleton_struct = Program.to((SINGLETON_TOP_LAYER_MOD_HASH, (launcher_id, SINGLETON_LAUNCHER_MOD_HASH)))
    return SINGLETON_TOP_LAYER_MOD.curry(singleton_struct, inner_puzzle_hash).get_tree_hash(inner_puzzle_hash)


def program_to_metadata(program: Program) -> Dict:
    """
    Convert a program to a metadata dict
    :param program: Chialisp program contains the metadata
    :return: Metadata dict
    """
    metadata = {}
    for key, val in program.as_python():
        metadata[str(key, "utf-8")] = str(val, "utf-8")
    return metadata


def get_did_info_from_coin_spend(coin: Coin, parent_cs: CoinSpend) -> Optional[dict]:
    parent_coin = parent_cs.coin
    puzzle = parent_cs.puzzle_reveal

    try:
        mod, curried_args_pz = puzzle.uncurry()
        if mod != SINGLETON_TOP_LAYER_MOD:
            return None
        singleton_inner_puzzle = curried_args_pz.rest().first()
        mod, curried_args_pz = singleton_inner_puzzle.uncurry()
        if mod != DID_INNERPUZ_MOD:
            return None
        curried_args = curried_args_pz.as_iter()
    except Exception:
        return None

    solution = Program.fromhex(parent_cs['solution'])

    p2_puzzle, recovery_list_hash, num_verification, singleton_struct, metadata = curried_args
    recovery_list_hash = recovery_list_hash.as_atom()

    p2_puzzle_hash = p2_puzzle.get_tree_hash()

    launcher_id = singleton_struct.rest().first().as_atom()

    inner_solution = solution.rest().rest().first()
    recovery_list = []
    if recovery_list_hash != Program.to([]).get_tree_hash():
        for did in inner_solution.rest().rest().rest().rest().rest().as_python():
            recovery_list.append(did[0])

    return {
        'did_id': launcher_id,
        'coin': coin,
        'p2_puzzle_hash': p2_puzzle_hash,
        'recovery_list_hash': recovery_list_hash,
        'recovery_list': recovery_list,
        'num_verification': num_verification.as_int(),
        'metadata': metadata,
        'lineage_proof': LineageProof(parent_coin.parent_coin_info, singleton_inner_puzzle.get_tree_hash(),
                                      parent_coin.amount)
    }
