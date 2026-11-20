// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Test} from "forge-std/Test.sol";

import {ParticipantRegistry} from "../src/ParticipantRegistry.sol";
import {BatchToken} from "../src/BatchToken.sol";
import {IncidentRegistry} from "../src/IncidentRegistry.sol";
import {IParticipantRegistry} from "../src/interfaces/IParticipantRegistry.sol";
import {IBatchToken} from "../src/interfaces/IBatchToken.sol";

/// @notice Shared fixture for the three contracts
abstract contract Fixture is Test {
    ParticipantRegistry internal registry;
    BatchToken internal batch;
    IncidentRegistry internal incidents;

    address internal verifier = makeAddr("verifier");
    address internal oracle = makeAddr("oracle");
    address internal manufacturer = makeAddr("manufacturer");
    address internal distributor = makeAddr("distributor");
    address internal pharmacy = makeAddr("pharmacy");
    address internal pharmacyTwo = makeAddr("pharmacyTwo");
    address internal regulator = makeAddr("regulator");
    address internal outsider = makeAddr("outsider");

    bytes32 internal constant PRODUCT = keccak256("PRODUCT-AMOX-500");
    bytes32 internal constant META = keccak256("ipfs-batch-document");
    bytes2 internal constant CITY_KY = "KY";
    bytes2 internal constant CITY_LV = "LV";
    uint64 internal constant SERIAL = 1001;

    function setUp() public virtual {
        vm.warp(1_700_000_000);
        registry = new ParticipantRegistry(address(this), verifier);
        batch = new BatchToken(address(this), registry, oracle, 7_000);
        incidents = new IncidentRegistry(
            address(this), verifier, registry, IBatchToken(address(batch)), oracle
        );

        batch.grantRole(batch.INCIDENT_ROLE(), address(incidents));

        vm.startPrank(verifier);
        registry.register(
            manufacturer, IParticipantRegistry.Kind.Manufacturer, keccak256("lic-m"), CITY_KY
        );
        registry.register(
            distributor, IParticipantRegistry.Kind.Distributor, keccak256("lic-d"), CITY_KY
        );
        registry.register(pharmacy, IParticipantRegistry.Kind.Pharmacy, keccak256("lic-p"), CITY_LV);
        registry.register(
            pharmacyTwo, IParticipantRegistry.Kind.Pharmacy, keccak256("lic-p2"), CITY_LV
        );
        registry.register(
            regulator, IParticipantRegistry.Kind.Regulator, keccak256("lic-r"), CITY_KY
        );
        vm.stopPrank();
    }

    function _mintDefault() internal returns (uint256 tokenId) {
        vm.prank(manufacturer);
        tokenId =
            batch.mint(PRODUCT, SERIAL, uint64(block.timestamp + 365 days), 1_000, META, CITY_KY);
    }

    function _shipToDistributor() internal returns (uint256 tokenId) {
        tokenId = _mintDefault();
        vm.prank(manufacturer);
        batch.initiateCustody(tokenId, distributor, CITY_KY);
        vm.prank(distributor);
        batch.acceptCustody(tokenId);
    }

    function _shipToPharmacy() internal returns (uint256 tokenId) {
        tokenId = _shipToDistributor();
        vm.prank(distributor);
        batch.initiateCustody(tokenId, pharmacy, CITY_LV);
        vm.prank(pharmacy);
        batch.acceptCustody(tokenId);
    }
}
