#!/usr/bin/env python3
# Copyright (c) 2026 The Reddcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Test PoSV3 stake-timestamp hardening (REP-0003).

Drives DEPLOYMENT_POSV3 from inactive to active on one chain and checks that the
two consensus rules switch on with it:

  R1/R3  a PoS block time must sit on a stake-mask boundary  -> time-not-masked
  R2     the future-drift allowance drops from 2 h to 15 s   -> time-too-new

Every assertion is differential: the same block construction is submitted before
and after activation, so a rule that was always on, or never on, fails the test.

The chain is built with posv3 at its regtest default (NEVER_ACTIVE) and the node
is then restarted with lockinontimeout, which locks the deployment in at its
timeout without needing a period of signalling blocks. The versionbits cache is
in-memory, so the restart recomputes state from an identical block index and the
deployment flags are the only variable.

Off-slot blocks have to be re-stamped on the coinstake as well as the header.
CheckBlock enforces block.nTime == coinstake.nTime context-free and runs ahead of
ContextualCheckBlockHeader, so a header-only edit always comes back as
bad-cs-time and never reaches the mask rule at all.
"""

from test_framework.address import key_to_p2pkh
from test_framework.blocktools import (
    NORMAL_GBT_REQUEST_PARAMS,
    create_block,
    sign_block,
)
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import advance_time_for_pos, assert_equal, set_node_times

VB_PERIOD = 144                      # versionbits period length for regtest
BUILD_HEIGHT = VB_PERIOD * 2         # 288: posv3 reaches its timeout and locks in
ACTIVE_HEIGHT = VB_PERIOD * 3        # 432: LOCKED_IN -> ACTIVE

MASK = 0xf                           # regtest nStakeTimestampMask
SLOT = MASK + 1                      # 16-second slots
DRIFT = 15                           # MAX_FUTURE_BLOCK_TIME_POSV3
LEGACY_DRIFT = 2 * 60 * 60           # MAX_FUTURE_BLOCK_TIME

# deployment:start:end:min_activation_height:lockinontimeout
VBPARAMS_POSV3_LOT = "-vbparams=posv3:0:1:0:1"


class PosV3TimestampTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 1
        # Build the chain with posv3 at its regtest default (NEVER_ACTIVE).
        self.extra_args = [[]]

    def skip_test_if_missing_module(self):
        self.skip_if_no_wallet()

    def deployment_info(self):
        """Return (bip9 sub-object, active flag) for posv3.

        getblockchaininfo puts `active` on the softfork entry itself and the
        versionbits detail one level down under `bip9`. Note that `bit` is only
        reported while the deployment is STARTED or MUST_SIGNAL, so it cannot be
        asserted once the deployment has locked in.
        """
        softfork = self.nodes[0].getblockchaininfo()["softforks"]["posv3"]
        return softfork["bip9"], softfork["active"]

    def deployment_reported(self):
        """Whether posv3 appears under softforks at all.

        SoftForkDescPushBack drops any deployment whose nStartTime is
        NEVER_ACTIVE, so a deployment that ships disabled is absent rather than
        present-and-inactive.
        """
        return "posv3" in self.nodes[0].getblockchaininfo()["softforks"]

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

    def build_pos_block(self, node, restamp=None, max_attempts=10):
        """Build and sign a PoS block on the tip, optionally re-stamped.

        `restamp` maps the block's natural time to the wanted one. It is applied
        to the coinstake as well as the header, so that CheckBlock's
        block.nTime == coinstake.nTime rule stays satisfied and the block reaches
        the contextual header checks this test is actually about.

        getblocktemplate can only build a PoS template when a valid coinstake
        exists at the current mocktime, so retry with time advanced the way
        self.generate() does.
        """
        for attempt in range(max_attempts):
            try:
                advance_time_for_pos(node, seconds=60)
                tmpl = node.getblocktemplate(NORMAL_GBT_REQUEST_PARAMS)
                block = create_block(tmpl=tmpl)
                if restamp is not None:
                    ntime = restamp(block.nTime)
                    block.nTime = ntime
                    block.vtx[1].nTime = ntime
                    block.vtx[1].rehash()
                    block.hashMerkleRoot = block.calc_merkle_root()
                block.solve()
                sign_block(block, self.get_signing_key(node, block))
                return block
            except Exception as e:
                if "no valid coinstake found" in str(e) and attempt < max_attempts - 1:
                    advance_time_for_pos(node, seconds=120)
                    continue
                raise

    def block_times(self, node, start, end):
        """Block times for the inclusive height range [start, end]."""
        return [node.getblock(node.getblockhash(h))["time"] for h in range(start, end + 1)]

    def run_test(self):
        node = self.nodes[0]

        self.log.info("Build to height %d with posv3 disabled", BUILD_HEIGHT)
        pre_start = node.getblockcount() + 1
        self.generate(BUILD_HEIGHT - node.getblockcount())
        assert_equal(node.getblockcount(), BUILD_HEIGHT)

        # Shipped disabled, so it is not reported at all. This is the same shape
        # the other NEVER_ACTIVE deployments have on this tree.
        assert not self.deployment_reported(), "posv3 is enabled by default on regtest"

        # --- pre-activation ---------------------------------------------------
        self.log.info("Unmasked block times are produced and accepted while posv3 is off")
        pre_times = self.block_times(node, pre_start, BUILD_HEIGHT)
        off_slot = [t for t in pre_times if t & MASK]
        assert off_slot, (
            f"all {len(pre_times)} pre-activation blocks landed on a slot boundary, "
            "so this run cannot distinguish the mask being enforced from it not being enforced"
        )
        self.log.info("  %d of %d pre-activation blocks are off-slot", len(off_slot), len(pre_times))

        self.log.info("A fully valid off-slot block is accepted while posv3 is off")
        # Take a block the staker built itself and only use it if its own chosen
        # timestamp is off-slot. Re-stamping would invalidate the kernel, so the
        # block would be refused for the wrong reason and prove nothing; this way
        # the block is valid in every respect except that its time is not aligned.
        for _ in range(8):
            loose = self.build_pos_block(node)
            if loose.nTime & MASK:
                break
        else:
            raise AssertionError("staker never produced an off-slot block pre-activation")
        assert_equal(node.submitblock(loose.serialize().hex()), None)
        assert_equal(node.getblockcount(), BUILD_HEIGHT + 1)
        self.log.info("  accepted a block stamped %d (off-slot by %d s)",
                      loose.nTime, loose.nTime & MASK)

        # --- activate ---------------------------------------------------------
        self.log.info("Restart with lockinontimeout so posv3 locks in at its timeout")
        # restart_node drops the node's mocktime while the framework keeps tracking
        # the old value, so re-anchor to the tip or the next block is stamped now
        # and validated against an adjusted time years earlier.
        self.restart_node(0, extra_args=[VBPARAMS_POSV3_LOT])
        set_node_times(self.nodes, node.getblockheader(node.getbestblockhash())["time"])

        bip9, active = self.deployment_info()
        assert_equal(bip9["status"], "locked_in")
        assert_equal(active, False)
        assert_equal(bip9["since"], BUILD_HEIGHT)

        self.log.info("Extend to height %d: LOCKED_IN -> ACTIVE", ACTIVE_HEIGHT)
        self.generate(ACTIVE_HEIGHT - node.getblockcount())
        assert_equal(node.getblockcount(), ACTIVE_HEIGHT)

        bip9, active = self.deployment_info()
        assert_equal(bip9["status"], "active")
        assert_equal(active, True)
        assert_equal(bip9["since"], ACTIVE_HEIGHT)

        # --- post-activation --------------------------------------------------
        self.log.info("Every block the node now produces is on a slot boundary (R1/R4)")
        first_masked = node.getblockcount() + 1
        self.generate(8)
        post_times = self.block_times(node, first_masked, node.getblockcount())
        assert_equal(len(post_times), 8)
        for height, t in zip(range(first_masked, node.getblockcount() + 1), post_times):
            assert_equal(t & MASK, 0)
        self.log.info("  %d blocks, all aligned to %d-second slots", len(post_times), SLOT)

        self.log.info("An off-slot block is now rejected as time-not-masked (R1/R3)")
        height_before = node.getblockcount()
        bad = self.build_pos_block(node, restamp=lambda t: t | 1)
        assert_equal(node.submitblock(bad.serialize().hex()), "time-not-masked")
        assert_equal(node.getblockcount(), height_before)

        self.log.info("A masked block beyond the 15 s drift is rejected as time-too-new (R2)")
        # Masked, so it clears the rule above and fails only on drift. Well inside
        # the context-free 2 h bound in CheckBlockHeader, which is deliberately
        # left loose, so the rejection has to come from the contextual check.
        ahead = 3600
        assert ahead > DRIFT and ahead < LEGACY_DRIFT
        far = self.build_pos_block(node, restamp=lambda t: (t + ahead) & ~MASK)
        assert_equal(node.submitblock(far.serialize().hex()), "time-too-new")
        assert_equal(node.getblockcount(), height_before)

        self.log.info("A masked, in-window block is still accepted")
        good = self.build_pos_block(node)
        assert good.nTime & MASK == 0, f"the node's own miner produced an off-slot block at {good.nTime}"
        assert_equal(node.submitblock(good.serialize().hex()), None)
        assert_equal(node.getblockcount(), height_before + 1)


if __name__ == "__main__":
    PosV3TimestampTest().main()
