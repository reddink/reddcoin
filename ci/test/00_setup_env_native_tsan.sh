#!/usr/bin/env bash
#
# Copyright (c) 2019-2020 The Bitcoin Core developers
# Copyright (c) 2019-2023 The Reddcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.

export LC_ALL=C.UTF-8

export CONTAINER_NAME=ci_native_tsan
# ubuntu:22.04 provides clang 14, whose ThreadSanitizer runtime aborts while
# formatting a report rather than printing it:
#
#   CHECK failed: sanitizer_common.h:494 "((i)) < ((size_))" (0xffffffff, 0x10)
#     AddLocation <- ReportRace <- FdClose <- closedir <- __os_dirlist
#
# sanitizer_common.h:494 is InternalMmapVector::operator[]'s bounds check,
# 0xffffffff is kInvalidTid and 0x10 the thread-registry size, so AddLocation
# took its file-descriptor branch, got back a descriptor with no recorded
# creating thread, and indexed the registry with -1. The process dies before
# any report is printed, which is why every occurrence has looked
# diagnostic-free and why the race: suppressions never fire: they are applied
# in OutputReport, which runs after AddLocation. See RED-57.
#
# Move to clang 18 on ubuntu:24.04, matching Bitcoin Core 28.x, which runs the
# same wallet_multiwallet workload with Berkeley DB under TSan. libclang-rt is
# named explicitly because the runtime is the component at fault here.
export DOCKER_NAME_TAG=ubuntu:24.04
export PACKAGES="clang-18 llvm-18 libclang-rt-18-dev libc++abi-18-dev libc++-18-dev python3-zmq"
export DEP_OPTS="CC=clang-18 CXX='clang++-18 -stdlib=libc++'"
export GOAL="install"
# Don't build with -Werror. clang enables -Wsuggest-override, and the depends
# boost 1.71 headers reach the compile through the plain -I depends include
# rather than the -isystem BOOST_CPPFLAGS, so their unmarked virtual overrides
# (against libc++'s std::error_category) would otherwise fail the build with
# -Werror=suggest-override. TSan's coverage is the runtime thread sanitizer,
# not compile-time -Werror, which the 64-bit non-libc++ tasks still carry.
export NO_WERROR=1
# Run two functional test suites at a time rather than the default four. Every
# node this job starts carries ThreadSanitizer's shadow memory, so four suites
# at once, each with several nodes, has repeatedly exhausted the runner and had
# the job SIGKILLed (exit 137) partway through. Measured: one suite alone peaks
# well under a gigabyte of the runner's 16 GB, so the ceiling is the
# concurrency rather than any single test. The build still uses MAKEJOBS.
export TEST_RUNNER_JOBS="-j2"
export BITCOIN_CONFIG="--enable-zmq --with-gui=no CPPFLAGS='-DARENA_DEBUG -DDEBUG_LOCKORDER' CXXFLAGS='-g' --with-sanitizers=thread CC=clang-18 CXX='clang++-18 -stdlib=libc++'"
