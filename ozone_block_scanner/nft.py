from typing import Tuple, Optional, Dict, Any

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.wallet.nft_wallet.uncurry_nft import UncurriedNFT


def metadata_to_program(metadata: Dict[bytes, Any]) -> Program:
    """
    Convert the metadata dict to a Chialisp program
    :param metadata: User defined metadata
    :return: Chialisp program
    """
    kv_list = []
    for key, value in metadata.items():
        kv_list.append((key, value))
    program: Program = Program.to(kv_list)
    return program


def program_to_metadata(program: Program) -> Dict[bytes, Any]:
    """
    Convert a program to a metadata dict
    :param program: Chialisp program contains the metadata
    :return: Metadata dict
    """
    metadata = {}
    for kv_pair in program.as_iter():
        metadata[kv_pair.first().as_atom()] = kv_pair.rest().as_python()
    return metadata


def prepend_value(key: bytes, value: Program, metadata: Dict[bytes, Any]) -> None:
    """
    Prepend a value to a list in the metadata
    :param key: Key of the field
    :param value: Value want to add
    :param metadata: Metadata
    :return:
    """

    if value != Program.to(0):
        if metadata[key] == b"":
            metadata[key] = [value.as_python()]
        else:
            metadata[key].insert(0, value.as_python())


def update_metadata(metadata: Program, update_condition: Program) -> Program:
    """
    Apply conditions of metadata updater to the previous metadata
    :param metadata: Previous metadata
    :param update_condition: Update metadata conditions
    :return: Updated metadata
    """
    new_metadata: Dict[bytes, Any] = program_to_metadata(metadata)
    uri: Program = update_condition.rest().rest().first()
    prepend_value(uri.first().as_python(), uri.rest(), new_metadata)
    return metadata_to_program(new_metadata)


def get_metadata_and_phs(unft: UncurriedNFT, solution: Program) -> Tuple[Program, bytes32]:
    conditions = unft.p2_puzzle.run(unft.get_innermost_solution(solution))
    metadata = unft.metadata
    puzhash_for_derivation: Optional[bytes32] = None
    for condition in conditions.as_iter():
        if condition.list_len() < 2:
            # invalid condition
            continue
        condition_code = condition.first().as_int()

        if condition_code == -24:
            # metadata update
            metadata = update_metadata(metadata, condition)
            metadata = Program.to(metadata)
        elif condition_code == 51 and condition.rest().rest().first().as_int() == 1:
            # destination puzhash
            if puzhash_for_derivation is not None:
                # ignore duplicated create coin conditions
                continue
            puzhash_for_derivation = condition.rest().first().as_atom()

    assert puzhash_for_derivation
    return metadata, puzhash_for_derivation


def get_new_owner_did(unft: UncurriedNFT, solution: Program) -> Optional[bytes32]:
    conditions = unft.p2_puzzle.run(unft.get_innermost_solution(solution))
    new_did_id = None
    for condition in conditions.as_iter():
        if condition.first().as_int() == -10:
            # this is the change owner magic condition
            new_did_id = condition.at("rf").atom
    return new_did_id


def get_nft_info_from_coin_spend(nft_coin: Coin, parent_cs: CoinSpend, address: bytes):
    puzzle = parent_cs.puzzle_reveal
    try:
        uncurried_nft = UncurriedNFT.uncurry(puzzle)
    except Exception as e:

        return None
    solution = Program.fromhex(parent_cs['solution'])

    # DID ID determines which NFT wallet should process the NFT
    new_did_id = None
    old_did_id = None
    # P2 puzzle hash determines if we should ignore the NFT
    old_p2_puzhash = uncurried_nft.p2_puzzle.get_tree_hash()
    metadata, new_p2_puzhash = get_metadata_and_phs(
        uncurried_nft,
        solution,
    )
    if uncurried_nft.supports_did:
        new_did_id = get_new_owner_did(uncurried_nft, solution)
        old_did_id = uncurried_nft.owner_did
        if new_did_id is None:
            new_did_id = old_did_id
        if new_did_id == b"":
            new_did_id = None

    if new_p2_puzhash != address:
        return
    parent_coin = Coin.from_json_dict(parent_cs['coin'])
    lineage_proof = LineageProof(parent_coin.parent_coin_info, uncurried_nft.nft_state_layer.get_tree_hash(),
                                 parent_coin.amount)
    return (uncurried_nft, new_did_id, new_p2_puzhash, lineage_proof)
