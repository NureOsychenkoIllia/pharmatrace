// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Fixture} from "./Fixture.sol";
import {ParticipantRegistry} from "../src/ParticipantRegistry.sol";
import {IParticipantRegistry} from "../src/interfaces/IParticipantRegistry.sol";

contract ParticipantRegistryTest is Fixture {
    event ParticipantRegistered(
        address indexed account, IParticipantRegistry.Kind kind, bytes32 licenseHash, bytes2 city
    );
    event LicenseUpdated(address indexed account, bytes32 oldHash, bytes32 newHash);
    event ParticipantSuspended(address indexed account);
    event ParticipantReinstated(address indexed account);
    event ParticipantRevoked(address indexed account, bytes32 reasonHash);

    function testRegisterParticipant() public {
        (
            IParticipantRegistry.Kind kind,
            IParticipantRegistry.Status status,
            bytes32 lic,
            bytes2 city,
            uint64 at
        ) = registry.participantOf(manufacturer);
        assertEq(uint256(kind), uint256(IParticipantRegistry.Kind.Manufacturer));
        assertEq(uint256(status), uint256(IParticipantRegistry.Status.Active));
        assertEq(lic, keccak256("lic-m"));
        assertEq(city, CITY_KY);
        assertEq(at, uint64(block.timestamp));
        assertEq(registry.participantCount(), 5);
    }

    function testRegisterEmitsEvent() public {
        address newPharmacy = makeAddr("newPharmacy");
        vm.expectEmit(true, false, false, true, address(registry));
        emit ParticipantRegistered(
            newPharmacy, IParticipantRegistry.Kind.Pharmacy, keccak256("lic-new"), CITY_LV
        );
        vm.prank(verifier);
        registry.register(
            newPharmacy, IParticipantRegistry.Kind.Pharmacy, keccak256("lic-new"), CITY_LV
        );
    }

    function testRegisterRevertsWithoutVerifierRole() public {
        vm.prank(outsider);
        vm.expectRevert();
        registry.register(outsider, IParticipantRegistry.Kind.Pharmacy, keccak256("x"), CITY_KY);
    }

    function testRegisterRevertsOnDuplicate() public {
        vm.prank(verifier);
        vm.expectRevert(
            abi.encodeWithSelector(ParticipantRegistry.AlreadyRegistered.selector, manufacturer)
        );
        registry.register(manufacturer, IParticipantRegistry.Kind.Pharmacy, keccak256("x"), CITY_KY);
    }

    function testRegisterRevertsOnInvalidKind() public {
        vm.prank(verifier);
        vm.expectRevert(ParticipantRegistry.InvalidKind.selector);
        registry.register(outsider, IParticipantRegistry.Kind.None, keccak256("x"), CITY_KY);
    }

    function testRegisterRevertsOnEmptyLicense() public {
        vm.prank(verifier);
        vm.expectRevert(ParticipantRegistry.EmptyLicense.selector);
        registry.register(outsider, IParticipantRegistry.Kind.Pharmacy, bytes32(0), CITY_KY);
    }

    function testRegisterRevertsOnEmptyCity() public {
        vm.prank(verifier);
        vm.expectRevert(ParticipantRegistry.InvalidCity.selector);
        registry.register(outsider, IParticipantRegistry.Kind.Pharmacy, keccak256("x"), bytes2(0));
    }

    function testRegisterRevertsOnZeroAddress() public {
        vm.prank(verifier);
        vm.expectRevert(ParticipantRegistry.ZeroAddress.selector);
        registry.register(address(0), IParticipantRegistry.Kind.Pharmacy, keccak256("x"), CITY_KY);
    }

    function testUpdateLicenseEmitsEvent() public {
        bytes32 oldHash = keccak256("lic-m");
        bytes32 newHash = keccak256("lic-m-2");
        vm.expectEmit(true, false, false, true, address(registry));
        emit LicenseUpdated(manufacturer, oldHash, newHash);
        vm.prank(verifier);
        registry.updateLicense(manufacturer, newHash);
        (,, bytes32 lic,,) = registry.participantOf(manufacturer);
        assertEq(lic, newHash);
    }

    function testUpdateLicenseRevertsOnZeroHash() public {
        vm.prank(verifier);
        vm.expectRevert(ParticipantRegistry.EmptyLicense.selector);
        registry.updateLicense(manufacturer, bytes32(0));
    }

    function testSuspendAndReinstate() public {
        vm.expectEmit(true, false, false, false, address(registry));
        emit ParticipantSuspended(distributor);
        vm.prank(verifier);
        registry.suspend(distributor);

        assertFalse(registry.isActive(distributor, IParticipantRegistry.Kind.Distributor));
        assertFalse(registry.isActiveParticipant(distributor));

        vm.expectEmit(true, false, false, false, address(registry));
        emit ParticipantReinstated(distributor);
        vm.prank(verifier);
        registry.reinstate(distributor);
        assertTrue(registry.isActive(distributor, IParticipantRegistry.Kind.Distributor));
    }

    function testSuspendRevertsForUnknownAccount() public {
        vm.prank(verifier);
        vm.expectRevert(
            abi.encodeWithSelector(ParticipantRegistry.NotRegistered.selector, outsider)
        );
        registry.suspend(outsider);
    }

    function testReinstateRevertsWhenActive() public {
        vm.prank(verifier);
        vm.expectRevert(
            abi.encodeWithSelector(
                ParticipantRegistry.WrongStatus.selector,
                distributor,
                IParticipantRegistry.Status.Active
            )
        );
        registry.reinstate(distributor);
    }

    function testRevokeIsPermanent() public {
        bytes32 reason = keccak256("forged-license");
        vm.expectEmit(true, false, false, true, address(registry));
        emit ParticipantRevoked(pharmacyTwo, reason);
        vm.prank(verifier);
        registry.revoke(pharmacyTwo, reason);

        assertFalse(registry.isActiveParticipant(pharmacyTwo));
        vm.prank(verifier);
        vm.expectRevert(
            abi.encodeWithSelector(
                ParticipantRegistry.WrongStatus.selector,
                pharmacyTwo,
                IParticipantRegistry.Status.Revoked
            )
        );
        registry.revoke(pharmacyTwo, reason);
    }

    function testRevokedCannotBeReinstated() public {
        vm.startPrank(verifier);
        registry.revoke(pharmacyTwo, keccak256("fraud"));
        vm.expectRevert(
            abi.encodeWithSelector(
                ParticipantRegistry.WrongStatus.selector,
                pharmacyTwo,
                IParticipantRegistry.Status.Revoked
            )
        );
        registry.reinstate(pharmacyTwo);
        vm.stopPrank();
    }

    function testIsActiveChecksKind() public {
        assertTrue(registry.isActive(pharmacy, IParticipantRegistry.Kind.Pharmacy));
        assertFalse(registry.isActive(pharmacy, IParticipantRegistry.Kind.Distributor));
        assertFalse(registry.isActive(outsider, IParticipantRegistry.Kind.Pharmacy));
    }

    function testAccountAtReturnsRegistrationOrder() public {
        assertEq(registry.accountAt(0), manufacturer);
        assertEq(registry.accountAt(3), pharmacyTwo);
    }

    function testPauseBlocksRegistration() public {
        address newcomer = makeAddr("newcomer");
        registry.pause();
        vm.prank(verifier);
        vm.expectRevert();
        registry.register(newcomer, IParticipantRegistry.Kind.Pharmacy, keccak256("x"), CITY_KY);

        registry.unpause();
        vm.prank(verifier);
        registry.register(newcomer, IParticipantRegistry.Kind.Pharmacy, keccak256("x"), CITY_KY);
        assertTrue(registry.isActiveParticipant(newcomer));
    }

    function testPauseOnlyByPauser() public {
        vm.prank(outsider);
        vm.expectRevert();
        registry.pause();
    }

    function testVerifierCanBeGrantedByAdmin() public {
        address secondVerifier = makeAddr("secondVerifier");
        registry.grantRole(registry.VERIFIER_ROLE(), secondVerifier);
        vm.prank(secondVerifier);
        registry.register(outsider, IParticipantRegistry.Kind.Pharmacy, keccak256("x"), CITY_KY);
        assertTrue(registry.isActiveParticipant(outsider));
    }

    function testConstructorRejectsZeroAdmin() public {
        vm.expectRevert(ParticipantRegistry.ZeroAddress.selector);
        new ParticipantRegistry(address(0), verifier);
    }

    function testConstructorRejectsZeroVerifier() public {
        vm.expectRevert(ParticipantRegistry.ZeroAddress.selector);
        new ParticipantRegistry(address(this), address(0));
    }

    function testReinstateUnknownAccount() public {
        vm.prank(verifier);
        vm.expectRevert(
            abi.encodeWithSelector(ParticipantRegistry.NotRegistered.selector, outsider)
        );
        registry.reinstate(outsider);
    }

    function testRevokeUnknownAccount() public {
        vm.prank(verifier);
        vm.expectRevert(
            abi.encodeWithSelector(ParticipantRegistry.NotRegistered.selector, outsider)
        );
        registry.revoke(outsider, keccak256("x"));
    }

    function testUpdateLicenseRejectsSuspendedParticipant() public {
        vm.startPrank(verifier);
        registry.suspend(pharmacy);
        vm.expectRevert(
            abi.encodeWithSelector(
                ParticipantRegistry.WrongStatus.selector,
                pharmacy,
                IParticipantRegistry.Status.Suspended
            )
        );
        registry.updateLicense(pharmacy, keccak256("new"));
        vm.stopPrank();
    }

    function testSuspendSuspendedParticipantReverts() public {
        vm.startPrank(verifier);
        registry.suspend(pharmacy);
        vm.expectRevert(
            abi.encodeWithSelector(
                ParticipantRegistry.WrongStatus.selector,
                pharmacy,
                IParticipantRegistry.Status.Suspended
            )
        );
        registry.suspend(pharmacy);
        vm.stopPrank();
    }
}
