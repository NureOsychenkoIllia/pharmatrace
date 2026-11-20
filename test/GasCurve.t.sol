// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {console2} from "forge-std/Test.sol";
import {Fixture} from "./Fixture.sol";

/// @notice Measures mint gas as the number of stored batches grows.
contract GasCurve is Fixture {
    function testGasVsRecords() public {
        uint256[5] memory marks = [uint256(1), 10, 20, 40, 60];
        uint256 markIndex = 0;
        for (uint256 i = 1; i <= 60; i++) {
            uint256 before = gasleft();
            vm.prank(manufacturer);
            batch.mint(
                PRODUCT, uint64(2_000 + i), uint64(block.timestamp + 365 days), 100, META, CITY_KY
            );
            uint256 used = before - gasleft();
            if (markIndex < marks.length && i == marks[markIndex]) {
                console2.log("mint_at", i, used);
                markIndex++;
            }
        }
    }
}
