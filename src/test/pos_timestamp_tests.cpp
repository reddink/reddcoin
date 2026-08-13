// Copyright (c) 2026 The Reddcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#include <chain.h>
#include <chainparams.h>
#include <consensus/params.h>
#include <deploymentstatus.h>
#include <pos/kernel.h>
#include <test/util/setup_common.h>

#include <boost/test/unit_test.hpp>

//! REP-0003: stake-timestamp mask and future-drift reduction.
BOOST_FIXTURE_TEST_SUITE(pos_timestamp_tests, BasicTestingSetup)

//! The mask quantises a timestamp by rounding it down onto a slot boundary.
BOOST_AUTO_TEST_CASE(stake_timestamp_mask_alignment)
{
    const int64_t mask = 0xf;
    BOOST_CHECK_EQUAL(mask + 1, 16);

    for (int i = 0; i < 256; ++i) {
        const int64_t t = 1793318400 + i;
        const int64_t aligned = t & ~mask;
        BOOST_CHECK_EQUAL(aligned & mask, 0);
        // Rounds down, and never by a whole slot or more.
        BOOST_CHECK(aligned <= t);
        BOOST_CHECK(t - aligned <= mask);
    }
}

//! The PoS chains quantise to 16-second slots. Signet configures no PoS
//! parameters at all, so it must keep the legacy 1-second granularity.
BOOST_AUTO_TEST_CASE(stake_timestamp_mask_chainparams)
{
    for (const auto& chain : {CBaseChainParams::MAIN, CBaseChainParams::TESTNET, CBaseChainParams::REGTEST}) {
        const auto params = CreateChainParams(*m_node.args, chain);
        BOOST_CHECK_EQUAL(params->GetConsensus().nStakeTimestampMask, 0xf);
    }
    const auto signet = CreateChainParams(*m_node.args, CBaseChainParams::SIGNET);
    BOOST_CHECK_EQUAL(signet->GetConsensus().nStakeTimestampMask, 0);
}

//! The security property the REP rests on: the tightened drift bound is
//! narrower than one slot, so a tip leaves at most one grindable future slot.
BOOST_AUTO_TEST_CASE(drift_bound_leaves_at_most_one_future_slot)
{
    const int64_t mask = 0xf;
    const int64_t slot = mask + 1;

    BOOST_CHECK_EQUAL(MAX_FUTURE_BLOCK_TIME_POSV3, 15);
    BOOST_CHECK_EQUAL(MAX_FUTURE_BLOCK_TIME, 2 * 60 * 60);
    // Strictly less than a slot. If this ever stopped holding, two future slots
    // could fit inside the drift allowance and grinding would come back.
    BOOST_CHECK(MAX_FUTURE_BLOCK_TIME_POSV3 < slot);

    // Sweep every phase within a slot: count the masked timestamps strictly in
    // the future but still inside the drift allowance.
    for (int64_t now = 1793318400; now < 1793318400 + 4 * slot; ++now) {
        int future_slots = 0;
        for (int64_t t = now + 1; t <= now + MAX_FUTURE_BLOCK_TIME_POSV3; ++t) {
            if ((t & mask) == 0) ++future_slots;
        }
        BOOST_CHECK_MESSAGE(future_slots <= 1, "now=" << now << " future_slots=" << future_slots);
    }

    // For contrast, the legacy bound admits 7,200 future candidates per tip.
    BOOST_CHECK_EQUAL(MAX_FUTURE_BLOCK_TIME, 7200);
}

//! The deployment gate, exercised through the helper consensus code calls.
BOOST_AUTO_TEST_CASE(posv3_deployment_gating)
{
    Consensus::Params active = CreateChainParams(*m_node.args, CBaseChainParams::REGTEST)->GetConsensus();
    active.vDeployments[Consensus::DEPLOYMENT_POSV3].nStartTime = Consensus::BIP9Deployment::ALWAYS_ACTIVE;

    Consensus::Params inactive = active;
    inactive.vDeployments[Consensus::DEPLOYMENT_POSV3].nStartTime = Consensus::BIP9Deployment::NEVER_ACTIVE;

    CBlockIndex prev;
    prev.nHeight = active.nLastPowHeight + 1;

    BOOST_CHECK(IsPoSV3Active(&prev, active));
    BOOST_CHECK(!IsPoSV3Active(&prev, inactive));
}

//! Shipped parameters must be inert: the deployment exists on every network but
//! cannot activate until an activation window is scheduled deliberately. The
//! change that schedules mainnet or testnet is expected to update this case,
//! which is the point: it cannot happen as a silent side effect.
BOOST_AUTO_TEST_CASE(posv3_ships_never_active)
{
    for (const auto& chain : {CBaseChainParams::MAIN, CBaseChainParams::TESTNET,
                              CBaseChainParams::SIGNET, CBaseChainParams::REGTEST}) {
        const auto params = CreateChainParams(*m_node.args, chain);
        const auto& dep = params->GetConsensus().vDeployments[Consensus::DEPLOYMENT_POSV3];
        BOOST_CHECK_EQUAL(dep.bit, 5);
        BOOST_CHECK_EQUAL(dep.nStartTime, Consensus::BIP9Deployment::NEVER_ACTIVE);
        BOOST_CHECK_EQUAL(dep.nTimeout, Consensus::BIP9Deployment::NO_TIMEOUT);
    }
}

//! IsPoSEraBlock tests the height of the block being connected, using the same
//! strict comparison against nLastPowHeight that validation.cpp already uses.
//! Header-only callers rely on this instead of CBlockHeader::IsProofOfStake(),
//! which only reports an attacker-chosen nVersion.
BOOST_AUTO_TEST_CASE(pos_era_predicate)
{
    Consensus::Params params = CreateChainParams(*m_node.args, CBaseChainParams::REGTEST)->GetConsensus();
    const int last_pow = params.nLastPowHeight;

    CBlockIndex prev;

    // pindexPrev at nLastPowHeight - 1 connects a block at nLastPowHeight: still PoW.
    prev.nHeight = last_pow - 1;
    BOOST_CHECK(!IsPoSEraBlock(&prev, params));

    // pindexPrev at nLastPowHeight connects the first PoS block.
    prev.nHeight = last_pow;
    BOOST_CHECK(IsPoSEraBlock(&prev, params));

    prev.nHeight = last_pow + 1;
    BOOST_CHECK(IsPoSEraBlock(&prev, params));

    BOOST_CHECK(!IsPoSEraBlock(nullptr, params));
}

//! REP-0003 deliberately leaves CheckCoinStakeTimestamp alone: it stays a
//! context-free equality, which is what makes masking the header time
//! transitively mask the coinstake time.
BOOST_AUTO_TEST_CASE(coinstake_timestamp_equality_unchanged)
{
    BOOST_CHECK(CheckCoinStakeTimestamp(1793318400, 1793318400));
    BOOST_CHECK(!CheckCoinStakeTimestamp(1793318400, 1793318416));
    BOOST_CHECK(!CheckCoinStakeTimestamp(1793318416, 1793318400));
    // Off-slot values are still accepted here; the mask is enforced contextually.
    BOOST_CHECK(CheckCoinStakeTimestamp(1793318401, 1793318401));
}

BOOST_AUTO_TEST_SUITE_END()
