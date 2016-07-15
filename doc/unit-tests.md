Compiling/running unit tests
------------------------------------

Unit tests will be automatically compiled if dependencies were met in configure
and tests weren't explicitly disabled.

After configuring, they can be run with 'make check'.

To run the reddcoind tests manually, launch src/test/test_reddcoin .

To add more reddcoind tests, add `BOOST_AUTO_TEST_CASE` functions to the existing
.cpp files in the test/ directory or add new .cpp files that
implement new BOOST_AUTO_TEST_SUITE sections.

To run the reddcoin-qt tests manually, launch src/qt/test/reddcoin-qt_test

To add more reddcoin-qt tests, add them to the `src/qt/test/` directory and
the `src/qt/test/test_main.cpp` file.
