// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {console2} from "forge-std/Test.sol";
import {Fixture} from "./Fixture.sol";
import {
    PackBaseline,
    PackOptimized,
    PackStorageRegistry,
    RevertStrings,
    RevertCustom
} from "./baseline/BatchTokenBaseline.sol";

/// @notice Isolated gas measurements for the two optimizations described in the report.
contract GasBenchmark is Fixture {
    PackBaseline internal unpacked;
    PackOptimized internal packed;
    PackStorageRegistry internal storageRegistry;
    RevertStrings internal strings;
    RevertCustom internal custom;

    function setUp() public override {
        super.setUp();
        unpacked = new PackBaseline(address(this), registry);
        packed = new PackOptimized(address(this), registry);
        storageRegistry = new PackStorageRegistry(address(this), registry);
        strings = new RevertStrings();
        custom = new RevertCustom();
    }

    function _mintUnpacked() internal {
        vm.prank(manufacturer);
        unpacked.mint(PRODUCT, SERIAL, uint64(block.timestamp + 365 days), 1_000, META, CITY_KY);
    }

    function _mintPacked() internal {
        vm.prank(manufacturer);
        packed.mint(PRODUCT, SERIAL, uint64(block.timestamp + 365 days), 1_000, META, CITY_KY);
    }

    function testGasMintUnpacked() public {
        uint256 before = gasleft();
        _mintUnpacked();
        console2.log("mint_unpacked", before - gasleft());
    }

    function testGasMintPacked() public {
        uint256 before = gasleft();
        _mintPacked();
        console2.log("mint_packed", before - gasleft());
    }

    function testGasMintStorageRegistry() public {
        uint256 before = gasleft();
        vm.prank(manufacturer);
        storageRegistry.mint(
            PRODUCT, SERIAL, uint64(block.timestamp + 365 days), 1_000, META, CITY_KY
        );
        console2.log("mint_storage_registry", before - gasleft());
    }

    function testGasRevertString() public {
        bytes memory data = abi.encodeWithSelector(RevertStrings.fail.selector);
        uint256 before = gasleft();
        (bool ok,) = address(strings).call(data);
        uint256 used = before - gasleft();
        assertFalse(ok);
        console2.log("revert_string", used);
    }

    function testGasRevertCustom() public {
        bytes memory data = abi.encodeWithSelector(RevertCustom.fail.selector);
        uint256 before = gasleft();
        (bool ok,) = address(custom).call(data);
        uint256 used = before - gasleft();
        assertFalse(ok);
        console2.log("revert_custom", used);
    }
}
