#!/usr/bin/env python3
# Copyright (c) 2026 The Reddcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""PoSV3 anti-grinding and fake-stake regression (REP-0003).

Runs with posv3 always active and asserts the security properties the mask and
the tightened drift bound are supposed to buy, rather than re-testing activation
(feature_posv3_timestamp.py covers that).

  grinding surface  every off-slot timestamp in a slot is refused, so a tip
                    offers one candidate rather than sixteen per second
  fake stake        no masked slot beyond +15 s is reachable, collapsing the
                    ~7,200 future candidates the legacy 2 h bound allowed
  header-level DoS  a mis-masked header is refused before the node will even
                    ask for the block body, so no kernel or signature work is
                    spent on it (R3)
  median lockout    GetMedianTimePast cannot be dragged past the wall clock
  parity            an honest staker still mines across the masked window (R5)

All the off-slot and future-stamped variants are derived from one valid template
block, re-stamped on both the header and the coinstake. CheckBlock enforces
block.nTime == coinstake.nTime context-free and runs before the contextual
header checks, so editing only the header would come back as bad-cs-time and
never reach the rules under test.
"""

from copy import deepcopy

from test_framework.address import key_to_p2pkh
from test_framework.blocktools import (
    NORMAL_GBT_REQUEST_PARAMS,
    create_block,
    sign_block,
)
from test_framework.messages import CBlockHeader, msg_headers
from test_framework.p2p import P2PDataStore
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import advance_time_for_pos, assert_equal, assert_greater_than

MASK = 0xf                     # regtest nStakeTimestampMask
SLOT = MASK + 1                # 16-second slots
DRIFT = 15                     # MAX_FUTURE_BLOCK_TIME_POSV3
LEGACY_DRIFT = 2 * 60 * 60     # MAX_FUTURE_BLOCK_TIME, the surface being removed

# nStartTime -1 is ALWAYS_ACTIVE.
VBPARAMS_POSV3_ALWAYS = "-vbparams=posv3:-1:9999999999"


class PosV3StakeGrindTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 1
        self.extra_args = [[VBPARAMS_POSV3_ALWAYS]]

    def skip_test_if_missing_module(self):
        self.skip_if_no_wallet()

    def get_signing_key(self, node, block):
        """Extract the signing key for a PoS block from the coinstake transaction."""
        decoded_tx = node.decoderawtransaction(block.vtx[1].serialize().hex())
        script_pubkey = decoded_tx["vout"][1]["scriptPubKey"]

        address = script_pubkey.get("address")
        if not address:
            addresses = script_pubkey.get("addresses", [])
            if addresses:
                address = addresses[0]
        if not address and script_pubkey.get("type") == "pubkey":
            asm = script_pubkey.get("asm", "").split()
            if asm and asm[0] != "OP_CHECKSIG":
                address = key_to_p2pkh(asm[0], main=False)

        assert address is not None, "could not resolve the coinstake signing address"
        return node.dumpprivkey(address)

    def build_pos_block(self, node, max_attempts=10):
        """Build and sign a valid PoS block on the current tip.

        getblocktemplate can only build a PoS template when a valid coinstake
        exists at the current mocktime, so retry with time advanced the way
        self.generate() does.
        """
        for attempt in range(max_attempts):
            try:
                advance_time_for_pos(node, seconds=60)
                tmpl = node.getblocktemplate(NORMAL_GBT_REQUEST_PARAMS)
                block = create_block(tmpl=tmpl)
                block.solve()
                sign_block(block, self.get_signing_key(node, block))
                return block
            except Exception as e:
                if "no valid coinstake found" in str(e) and attempt < max_attempts - 1:
                    advance_time_for_pos(node, seconds=120)
                    continue
                raise

    def restamp(self, node, block, ntime):
        """Copy `block` with a new timestamp on both the header and the coinstake."""
        clone = deepcopy(block)
        clone.nTime = ntime
        clone.vtx[1].nTime = ntime
        clone.vtx[1].rehash()
        clone.hashMerkleRoot = clone.calc_merkle_root()
        clone.rehash()
        clone.solve()
        sign_block(clone, self.get_signing_key(node, clone))
        return clone

    def run_test(self):
        node = self.nodes[0]
        peer = node.add_p2p_connection(P2PDataStore())

        self.log.info("Confirm posv3 is active for this chain")
        softfork = node.getblockchaininfo()["softforks"]["posv3"]
        assert_equal(softfork["active"], True)

        self.log.info("The node's own staker only produces masked blocks")
        first = node.getblockcount() + 1
        self.generate(6)
        for height in range(first, node.getblockcount() + 1):
            t = node.getblock(node.getblockhash(height))["time"]
            assert_equal(t & MASK, 0)

        base_block = self.build_pos_block(node)
        base_time = base_block.nTime
        assert_equal(base_time & MASK, 0)
        height_before = node.getblockcount()

        # --- grinding surface -------------------------------------------------
        self.log.info("Every off-slot timestamp within the slot is refused (R1)")
        for offset in range(1, SLOT):
            bad = self.restamp(node, base_block, base_time + offset)
            assert_equal(node.submitblock(bad.serialize().hex()), "time-not-masked")
            assert_equal(node.getblockcount(), height_before)
        self.log.info("  %d of %d timestamps per slot are unusable", SLOT - 1, SLOT)

        # --- fake stake / future stamping -------------------------------------
        self.log.info("No masked slot beyond the %d s drift bound is reachable (R2)", DRIFT)
        checked = 0
        for ahead in (SLOT, 2 * SLOT, 4 * SLOT, 600, 3600, LEGACY_DRIFT):
            ntime = (base_time + ahead) & ~MASK
            if ntime - base_time <= DRIFT:
                continue  # the single legal future slot, if this phase leaves one
            far = self.restamp(node, base_block, ntime)
            assert_equal(node.submitblock(far.serialize().hex()), "time-too-new")
            assert_equal(node.getblockcount(), height_before)
            checked += 1
        assert_greater_than(checked, 0)
        self.log.info("  rejected %d future slots, including the legacy +%d s bound",
                      checked, LEGACY_DRIFT)

        # The surface the REP removes, stated as a ratio: the legacy rules left
        # one future candidate per second across two hours.
        assert_greater_than(LEGACY_DRIFT, DRIFT)
        assert DRIFT < SLOT, "drift bound must stay narrower than one slot"

        # --- header-level rejection (R3) --------------------------------------
        # The fake-stake DoS path: a header alone, with no block body behind it.
        # The mask has to reject it on sight, or an attacker could make the node
        # spend kernel and signature work on garbage. Sending the header over p2p
        # rather than via submitblock is what lets us observe that the body was
        # never even requested.
        self.log.info("A mis-masked header is refused on sight and the peer is dropped (R3)")
        off_slot = self.restamp(node, base_block, base_time + 1)
        with node.assert_debug_log(expected_msgs=["time-not-masked", "invalid header received"]):
            peer.send_message(msg_headers([CBlockHeader(off_slot)]))
            # An invalid header is a 100-point misbehaviour, so the node drops the
            # peer instead of continuing the exchange.
            peer.wait_for_disconnect()
        assert off_slot.sha256 not in peer.getdata_requests, (
            "the node asked for the body of a header it should have rejected on sight"
        )
        assert_equal(node.getblockcount(), height_before)

        # --- median lockout ---------------------------------------------------
        self.log.info("GetMedianTimePast cannot be pushed past the clock")
        pre_median = node.getblockchaininfo()["mediantime"]
        self.generate(6)
        post_median = node.getblockchaininfo()["mediantime"]
        assert_greater_than(post_median, pre_median)

        tip_time = node.getblockheader(node.getbestblockhash())["time"]
        assert post_median <= tip_time, (post_median, tip_time)
        # The tip itself cannot have run ahead of the clock by more than the drift
        # bound, which is what stops an attacker walking the median away from
        # honest stakers.
        assert node.mocktime, "mocktime is not being tracked, so this check proves nothing"
        assert tip_time <= node.mocktime + DRIFT, (tip_time, node.mocktime)

        # --- parity (R5) ------------------------------------------------------
        self.log.info("An honest staker still mines across the masked window (R5)")
        before = node.getblockcount()
        self.generate(4)
        assert_equal(node.getblockcount(), before + 4)

        self.log.info("A valid masked block is still accepted")
        good = self.build_pos_block(node)
        assert_equal(good.nTime & MASK, 0)
        assert_equal(node.submitblock(good.serialize().hex()), None)
        assert_equal(node.getblockcount(), before + 5)


if __name__ == "__main__":
    PosV3StakeGrindTest().main()
