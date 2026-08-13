// Copyright (c) 2020 The Bitcoin Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.

#ifndef BITCOIN_DEPLOYMENTSTATUS_H
#define BITCOIN_DEPLOYMENTSTATUS_H

#include <chain.h>
#include <versionbits.h>

#include <limits>

/** Global cache for versionbits deployment status */
extern VersionBitsCache g_versionbitscache;

/** Determine if a deployment is active for the next block */
inline bool DeploymentActiveAfter(const CBlockIndex* pindexPrev, const Consensus::Params& params, Consensus::BuriedDeployment dep)
{
    assert(Consensus::ValidDeployment(dep));
    return (pindexPrev == nullptr ? 0 : pindexPrev->nHeight + 1) >= params.DeploymentHeight(dep);
}

inline bool DeploymentActiveAfter(const CBlockIndex* pindexPrev, const Consensus::Params& params, Consensus::DeploymentPos dep)
{
    assert(Consensus::ValidDeployment(dep));
    return ThresholdState::ACTIVE == g_versionbitscache.State(pindexPrev, params, dep);
}

/** Determine if a deployment is active for this block */
inline bool DeploymentActiveAt(const CBlockIndex& index, const Consensus::Params& params, Consensus::BuriedDeployment dep)
{
    assert(Consensus::ValidDeployment(dep));
    return index.nHeight >= params.DeploymentHeight(dep);
}

inline bool DeploymentActiveAt(const CBlockIndex& index, const Consensus::Params& params, Consensus::DeploymentPos dep)
{
    assert(Consensus::ValidDeployment(dep));
    return DeploymentActiveAfter(index.pprev, params, dep);
}

/** Determine if a deployment is enabled (can ever be active) */
inline bool DeploymentEnabled(const Consensus::Params& params, Consensus::BuriedDeployment dep)
{
    assert(Consensus::ValidDeployment(dep));
    return params.DeploymentHeight(dep) != std::numeric_limits<int>::max();
}

inline bool DeploymentEnabled(const Consensus::Params& params, Consensus::DeploymentPos dep)
{
    assert(Consensus::ValidDeployment(dep));
    return params.vDeployments[dep].nStartTime != Consensus::BIP9Deployment::NEVER_ACTIVE;
}

/**
 * REP-0003: is the block extending pindexPrev in the PoS era?
 *
 * Mirrors the tree's existing PoS-era tests in validation.cpp (ConnectBlock's
 * "pow-ended" check and the BIP30 loop), which both compare the block's own
 * height with strict `>` against nLastPowHeight.
 *
 * Callers that only hold a CBlockHeader must use this rather than
 * CBlockHeader::IsProofOfStake(), which merely reports nVersion >
 * POW_BLOCK_VERSION and is therefore attacker-chosen.
 */
inline bool IsPoSEraBlock(const CBlockIndex* pindexPrev, const Consensus::Params& params)
{
    return pindexPrev != nullptr && pindexPrev->nHeight + 1 > params.nLastPowHeight;
}

/** REP-0003: are the PoSV3 stake-timestamp rules active for a block extending pindexPrev? */
inline bool IsPoSV3Active(const CBlockIndex* pindexPrev, const Consensus::Params& params)
{
    return DeploymentActiveAfter(pindexPrev, params, Consensus::DEPLOYMENT_POSV3);
}

#endif // BITCOIN_DEPLOYMENTSTATUS_H
