#!/usr/bin/env python3
# Copyright (c) 2026 The Reddcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Test BIP8 lockinontimeout (REP-0002).

A deployment that is never signalled still activates at its timeout when
lockinontimeout is set, and never activates when it is not. The same chain is
replayed under all three configurations by restarting the node, so the only
variable is the deployment flags.

The chain is built with the deployment disabled (regtest testdummy defaults to
NEVER_ACTIVE), which is what makes every block non-signalling for bit 28 - the
node's own miner would otherwise set the bit as soon as the deployment reached
STARTED. The versionbits cache is in-memory, so each restart recomputes the
deployment state from the identical block index.

The opt-in mustsignal mode is driven end to end, STARTED -> MUST_SIGNAL ->
LOCKED_IN -> ACTIVE, which takes one period longer than minimal lot=true. Along
the way it checks that a non-signalling block is invalid inside the forced
period and valid again once it ends, that getblocktemplate hands out the bit as
a non-negotiable rule, and that every block the node's own miner produced during
the period carries the bit.
"""

from test_framework.address import key_to_p2pkh
from test_framework.blocktools import (
    NORMAL_GBT_REQUEST_PARAMS,
    create_block,
    sign_block,
)
from test_framework.test_framework import BitcoinTestFramework
from test_framework.util import advance_time_for_pos, assert_equal, set_node_times

VB_PERIOD = 144        # versionbits period length for regtest
VB_TOP_BITS = 0x20000000
VB_TESTDUMMY_BIT = 28  # regtest testdummy deployment bit

# Period boundaries the deployment moves on. With start=0 and timeout=1 the
# deployment is STARTED at the first boundary and past its timeout at the next.
#
# getblockchaininfo reports the state of the block AFTER the tip, so a tip at
# height N-1 already reports the state of the period beginning at N.
TIMEOUT_HEIGHT = VB_PERIOD * 2      # 288: STARTED -> LOCKED_IN / MUST_SIGNAL / FAILED
LOCKIN_HEIGHT = VB_PERIOD * 3       # 432: MUST_SIGNAL -> LOCKED_IN, and lot-only ACTIVE
MUSTSIGNAL_ACTIVE_HEIGHT = VB_PERIOD * 4  # 576: LOCKED_IN -> ACTIVE, one period later than lot-only

# Highest tip that still reports must_signal. Blocks up to LOCKIN_HEIGHT - 1 are
# inside the forced-signalling period, but a tip there already reports the next
# period's state, so the observable window ends one block earlier.
MUSTSIGNAL_LAST_HEIGHT = LOCKIN_HEIGHT - 2

# deployment:start:end:min_activation_height:lockinontimeout:mustsignal
VBPARAMS_LOT_MUSTSIGNAL = "-vbparams=testdummy:0:1:0:1:1"
VBPARAMS_LOT = "-vbparams=testdummy:0:1:0:1"
VBPARAMS_NO_LOT = "-vbparams=testdummy:0:1:0:0"


class VersionBitsLockinOnTimeoutTest(BitcoinTestFramework):
    def set_test_params(self):
        self.num_nodes = 1
        # Build the chain with testdummy at its regtest default (NEVER_ACTIVE) so
        # that no block signals bit 28.
        self.extra_args = [[]]

    def skip_test_if_missing_module(self):
        self.skip_if_no_wallet()

    def deployment_info(self):
        """Return (bip9 sub-object, active flag).

        getblockchaininfo puts `active` on the softfork entry itself and the
        versionbits detail one level down under `bip9`.
        """
        softfork = self.nodes[0].getblockchaininfo()["softforks"]["testdummy"]
        return softfork["bip9"], softfork["active"]

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

    def restart_with(self, vbparams):
        """Restart the node with new deployment flags, keeping one clock in play.

        restart_node drops the node's mocktime, so it falls back to wall-clock time
        while the framework still tracks the old value. Mixing the two produces a
        block stamped now and validated against an adjusted time years earlier,
        which fails as time-too-new. Re-anchor mocktime to the tip after restarting.
        """
        self.restart_node(0, extra_args=[vbparams])
        node = self.nodes[0]
        set_node_times(self.nodes, node.getblockheader(node.getbestblockhash())["time"])

    def build_block(self, node, version, max_attempts=10):
        """Build and sign a PoS block on top of the tip with an explicit nVersion.

        getblocktemplate can only build a PoS template if a valid coinstake exists
        at the current mocktime, so retry with time advanced the way self.generate()
        does. Without this the call fails outright whenever the tip was just mined.
        """
        for attempt in range(max_attempts):
            try:
                advance_time_for_pos(node, seconds=60)
                tmpl = node.getblocktemplate(NORMAL_GBT_REQUEST_PARAMS)
                block = create_block(tmpl=tmpl, version=version)
                block.solve()
                sign_block(block, self.get_signing_key(node, block))
                return block
            except Exception as e:
                if "no valid coinstake found" in str(e) and attempt < max_attempts - 1:
                    advance_time_for_pos(node, seconds=120)
                    continue
                raise

    def run_test(self):
        node = self.nodes[0]

        self.log.info("Build a chain to height %d with testdummy disabled, so nothing signals bit %d",
                      TIMEOUT_HEIGHT, VB_TESTDUMMY_BIT)
        self.generate(TIMEOUT_HEIGHT - node.getblockcount())
        assert_equal(node.getblockcount(), TIMEOUT_HEIGHT)

        # --- mustsignal: STARTED -> MUST_SIGNAL -> LOCKED_IN -> ACTIVE -----------
        self.log.info("Restart with lockinontimeout=1, mustsignal=1")
        self.restart_with(VBPARAMS_LOT_MUSTSIGNAL)

        bip9, active = self.deployment_info()
        assert_equal(bip9["status"], "must_signal")
        assert_equal(active, False)
        assert_equal(bip9["bit"], VB_TESTDUMMY_BIT)
        assert_equal(bip9["since"], TIMEOUT_HEIGHT)

        self.log.info("getblocktemplate must force the bit and list the rule as non-negotiable")
        tmpl = node.getblocktemplate(NORMAL_GBT_REQUEST_PARAMS)
        assert tmpl["version"] & (1 << VB_TESTDUMMY_BIT), "GBT cleared a mandatory signalling bit"
        assert "testdummy" in tmpl["rules"], "MUST_SIGNAL rule missing from GBT rules"
        assert "testdummy" not in tmpl["vbavailable"], "MUST_SIGNAL bit offered as optional"

        self.log.info("A non-signalling block inside MUST_SIGNAL is rejected")
        bad_block = self.build_block(node, VB_TOP_BITS)
        assert_equal(node.submitblock(bad_block.serialize().hex()), "must-signal")
        assert_equal(node.getblockcount(), TIMEOUT_HEIGHT)

        self.log.info("A block from the node's own miner is accepted by the node's own rule")
        self.generate(1)
        assert_equal(node.getblockcount(), TIMEOUT_HEIGHT + 1)
        tip_version = node.getblock(node.getbestblockhash())["version"]
        assert tip_version & (1 << VB_TESTDUMMY_BIT), "the node built a block that fails its own rule"
        assert_equal(self.deployment_info()[0]["status"], "must_signal")

        self.log.info("Mine out the rest of the MUST_SIGNAL period, to height %d", MUSTSIGNAL_LAST_HEIGHT)
        self.generate(MUSTSIGNAL_LAST_HEIGHT - node.getblockcount())
        assert_equal(self.deployment_info()[0]["status"], "must_signal")

        # Every block the node produced in this period had to carry the bit, or the
        # rule above would have orphaned it. Check the whole period, not a sample.
        for height in range(TIMEOUT_HEIGHT + 1, MUSTSIGNAL_LAST_HEIGHT + 1):
            version = node.getblock(node.getblockhash(height))["version"]
            assert version & (1 << VB_TESTDUMMY_BIT), f"block {height} in MUST_SIGNAL did not signal"

        self.log.info("Cross the period boundary at %d: MUST_SIGNAL -> LOCKED_IN", LOCKIN_HEIGHT)
        self.generate(LOCKIN_HEIGHT - node.getblockcount())
        assert_equal(node.getblockcount(), LOCKIN_HEIGHT)

        bip9, active = self.deployment_info()
        assert_equal(bip9["status"], "locked_in")
        assert_equal(active, False)
        assert_equal(bip9["since"], LOCKIN_HEIGHT)

        self.log.info("Forced signalling is over: a non-signalling block is now accepted")
        ok_block = self.build_block(node, VB_TOP_BITS)
        assert_equal(node.submitblock(ok_block.serialize().hex()), None)
        assert_equal(node.getblockcount(), LOCKIN_HEIGHT + 1)

        self.log.info("Extend to height %d: LOCKED_IN -> ACTIVE", MUSTSIGNAL_ACTIVE_HEIGHT)
        self.generate(MUSTSIGNAL_ACTIVE_HEIGHT - node.getblockcount())
        assert_equal(node.getblockcount(), MUSTSIGNAL_ACTIVE_HEIGHT)

        bip9, active = self.deployment_info()
        assert_equal(bip9["status"], "active")
        assert_equal(active, True)
        assert_equal(bip9["since"], MUSTSIGNAL_ACTIVE_HEIGHT)

        # --- minimal lot=true: STARTED -> LOCKED_IN -> ACTIVE one period sooner ---
        self.log.info("Restart with lockinontimeout=1, mustsignal=0 (the recommended default)")
        self.restart_with(VBPARAMS_LOT)

        # Same chain, but with no forced-signalling period to pass through the
        # deployment locked in at the timeout and activated a whole period earlier.
        bip9, active = self.deployment_info()
        assert_equal(bip9["status"], "active")
        assert_equal(active, True)
        assert_equal(bip9["since"], LOCKIN_HEIGHT)

        # --- BIP9 (lot=false): the same chain never activates --------------------
        self.log.info("Restart with lockinontimeout=0: the identical chain must fail instead")
        self.restart_with(VBPARAMS_NO_LOT)

        bip9, active = self.deployment_info()
        assert_equal(bip9["status"], "failed")
        assert_equal(active, False)
        assert_equal(bip9["since"], TIMEOUT_HEIGHT)


if __name__ == "__main__":
    VersionBitsLockinOnTimeoutTest().main()
