// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Fixture} from "./Fixture.sol";
import {BatchToken} from "../src/BatchToken.sol";
import {ParticipantRegistry} from "../src/ParticipantRegistry.sol";
import {IParticipantRegistry} from "../src/interfaces/IParticipantRegistry.sol";

contract BatchTokenTest is Fixture {
    event BatchMinted(
        uint256 indexed tokenId,
        bytes32 indexed productId,
        uint64 serial,
        address indexed manufacturer,
        uint128 quantity,
        bytes32 metadataHash
    );
    event CustodyAccepted(uint256 indexed tokenId, address indexed from, address indexed to);
    event CustodyRejected(uint256 indexed tokenId, address indexed from, address indexed to);
    event BatchSplit(
        uint256 indexed parentId,
        uint256[] childIds,
        uint128[] quantities,
        address indexed custodian
    );
    event BatchRecalled(uint256 indexed tokenId, address indexed by, bytes32 reasonHash);
    event AnomalyRecorded(
        uint256 indexed tokenId,
        uint16 scoreBps,
        bytes32 modelVersion,
        bytes32 dataHash,
        uint8 anomalyType
    );

    function testMintWritesBatch() public {
        uint256 id = _mintDefault();
        BatchToken.Batch memory b = batch.getBatch(id);
        assertEq(id, 1);
        assertEq(b.productId, PRODUCT);
        assertEq(b.serial, SERIAL);
        assertEq(b.manufacturer, manufacturer);
        assertEq(b.custodian, manufacturer);
        assertEq(uint256(b.state), uint256(BatchToken.State.Created));
        assertEq(b.quantity, 1_000);
        assertEq(b.metadataHash, META);
        assertEq(batch.ownerOf(id), manufacturer);
        assertEq(batch.batchCount(), 1);
    }

    function testMintEmitsEvent() public {
        vm.expectEmit(true, true, true, true, address(batch));
        emit BatchMinted(1, PRODUCT, SERIAL, manufacturer, 1_000, META);
        _mintDefault();
    }

    function testMintRevertsForNonManufacturer() public {
        vm.prank(distributor);
        vm.expectRevert(abi.encodeWithSelector(BatchToken.NotManufacturer.selector, distributor));
        batch.mint(PRODUCT, SERIAL, uint64(block.timestamp + 1 days), 10, META, CITY_KY);
    }

    function testMintRevertsOnDuplicateSerial() public {
        _mintDefault();
        vm.prank(manufacturer);
        vm.expectRevert(
            abi.encodeWithSelector(BatchToken.DuplicateSerial.selector, PRODUCT, SERIAL)
        );
        batch.mint(PRODUCT, SERIAL, uint64(block.timestamp + 1 days), 10, META, CITY_KY);
    }

    function testMintRevertsOnZeroQuantity() public {
        vm.prank(manufacturer);
        vm.expectRevert(BatchToken.InvalidQuantity.selector);
        batch.mint(PRODUCT, 77, uint64(block.timestamp + 1 days), 0, META, CITY_KY);
    }

    function testMintRevertsOnExpiredBatch() public {
        vm.prank(manufacturer);
        vm.expectRevert(BatchToken.InvalidExpiry.selector);
        batch.mint(PRODUCT, 77, uint64(block.timestamp), 10, META, CITY_KY);
    }

    function testVerifySerial() public {
        uint256 id = _mintDefault();
        assertEq(batch.verifySerial(PRODUCT, SERIAL), id);
        assertEq(batch.verifySerial(PRODUCT, 9999), 0);
        assertEq(batch.verifySerial(keccak256("other"), SERIAL), 0);
    }

    function testInitiateCustody() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        batch.initiateCustody(id, distributor, CITY_KY);
        BatchToken.Batch memory b = batch.getBatch(id);
        assertEq(uint256(b.state), uint256(BatchToken.State.InTransit));
        assertEq(b.pendingRecipient, distributor);
        assertEq(b.custodian, manufacturer);
    }

    function testAcceptCustody() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        batch.initiateCustody(id, distributor, CITY_KY);
        vm.expectEmit(true, true, true, false, address(batch));
        emit CustodyAccepted(id, manufacturer, distributor);
        vm.prank(distributor);
        batch.acceptCustody(id);

        BatchToken.Batch memory b = batch.getBatch(id);
        assertEq(uint256(b.state), uint256(BatchToken.State.Delivered));
        assertEq(b.custodian, distributor);
        assertEq(b.pendingRecipient, address(0));
        assertEq(batch.ownerOf(id), distributor);
    }

    function testRejectCustodyReturnsToSender() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        batch.initiateCustody(id, distributor, CITY_KY);
        vm.expectEmit(true, true, true, false, address(batch));
        emit CustodyRejected(id, manufacturer, distributor);
        vm.prank(distributor);
        batch.rejectCustody(id);

        BatchToken.Batch memory b = batch.getBatch(id);
        assertEq(uint256(b.state), uint256(BatchToken.State.Delivered));
        assertEq(b.custodian, manufacturer);
        assertEq(b.pendingRecipient, address(0));
    }

    function testOnlyCustodianInitiates() public {
        uint256 id = _mintDefault();
        vm.prank(distributor);
        vm.expectRevert(abi.encodeWithSelector(BatchToken.NotCustodian.selector, id, distributor));
        batch.initiateCustody(id, distributor, CITY_KY);
    }

    function testPharmacyCannotForwardBatch() public {
        uint256 id = _shipToPharmacy();
        vm.prank(pharmacy);
        vm.expectRevert(abi.encodeWithSelector(BatchToken.InvalidRecipient.selector, pharmacy));
        batch.initiateCustody(id, pharmacyTwo, CITY_LV);
    }

    function testCannotTransferToManufacturer() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        vm.expectRevert(abi.encodeWithSelector(BatchToken.InvalidRecipient.selector, manufacturer));
        batch.initiateCustody(id, manufacturer, CITY_KY);
    }

    function testCannotTransferToSuspendedParticipant() public {
        uint256 id = _mintDefault();
        vm.prank(verifier);
        registry.suspend(distributor);
        vm.prank(manufacturer);
        vm.expectRevert(abi.encodeWithSelector(BatchToken.InvalidRecipient.selector, distributor));
        batch.initiateCustody(id, distributor, CITY_KY);
    }

    function testAcceptOnlyByPendingRecipient() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        batch.initiateCustody(id, distributor, CITY_KY);
        vm.prank(pharmacy);
        vm.expectRevert(
            abi.encodeWithSelector(BatchToken.NotPendingRecipient.selector, id, pharmacy)
        );
        batch.acceptCustody(id);
    }

    function testErc721TransferDisabled() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        vm.expectRevert(BatchToken.UseCustodyWorkflow.selector);
        batch.transferFrom(manufacturer, distributor, id);
    }

    function testErc721SafeTransferDisabled() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        vm.expectRevert(BatchToken.UseCustodyWorkflow.selector);
        batch.safeTransferFrom(manufacturer, distributor, id);
    }

    function testSplitReducesParentAndMintsChildren() public {
        uint256 id = _mintDefault();
        uint128[] memory parts = new uint128[](2);
        parts[0] = 400;
        parts[1] = 600;
        vm.prank(manufacturer);
        uint256[] memory children = batch.split(id, parts);

        BatchToken.Batch memory parent = batch.getBatch(id);
        assertEq(parent.quantity, 0);
        assertEq(children.length, 2);
        assertEq(batch.ownerOf(children[0]), manufacturer);
        assertEq(children[0], 2);
        BatchToken.Batch memory child = batch.getBatch(children[0]);
        assertEq(child.parentId, id);
        assertEq(child.quantity, 400);
        assertEq(child.serial, 1_000_001);
        assertEq(child.productId, PRODUCT);
        assertEq(child.metadataHash, META);
        assertEq(uint256(child.state), uint256(BatchToken.State.Created));
        assertEq(batch.verifySerial(PRODUCT, 1_000_001), children[0]);
    }

    function testSplitEmitsEvent() public {
        uint256 id = _mintDefault();
        uint128[] memory parts = new uint128[](1);
        parts[0] = 10;
        uint256[] memory expected = new uint256[](1);
        expected[0] = 2;
        vm.expectEmit(true, false, false, true, address(batch));
        emit BatchSplit(id, expected, parts, manufacturer);
        vm.prank(manufacturer);
        batch.split(id, parts);
    }

    function testSplitRevertsWhenTooLarge() public {
        uint256 id = _mintDefault();
        uint128[] memory parts = new uint128[](1);
        parts[0] = 1_001;
        vm.prank(manufacturer);
        vm.expectRevert(BatchToken.InvalidSplit.selector);
        batch.split(id, parts);
    }

    function testSplitRevertsWhenEmpty() public {
        uint256 id = _mintDefault();
        uint128[] memory parts = new uint128[](0);
        vm.prank(manufacturer);
        vm.expectRevert(BatchToken.InvalidSplit.selector);
        batch.split(id, parts);
    }

    function testSplitRevertsWhenInTransit() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        batch.initiateCustody(id, distributor, CITY_KY);
        uint128[] memory parts = new uint128[](1);
        parts[0] = 10;
        vm.prank(manufacturer);
        vm.expectRevert(
            abi.encodeWithSelector(BatchToken.InvalidState.selector, id, BatchToken.State.InTransit)
        );
        batch.split(id, parts);
    }

    function testSplitOnlyByCustodian() public {
        uint256 id = _mintDefault();
        uint128[] memory parts = new uint128[](1);
        parts[0] = 10;
        vm.prank(distributor);
        vm.expectRevert(abi.encodeWithSelector(BatchToken.NotCustodian.selector, id, distributor));
        batch.split(id, parts);
    }

    function testDispenseAtPharmacy() public {
        uint256 id = _shipToPharmacy();
        bytes32 commitment = keccak256("patient-pseudonym");
        vm.prank(pharmacy);
        batch.dispense(id, commitment);
        assertEq(uint256(batch.stateOf(id)), uint256(BatchToken.State.Dispensed));
        assertEq(batch.patientCommitment(id), commitment);
    }

    function testDispenseRevertsForDistributor() public {
        uint256 id = _shipToDistributor();
        vm.prank(distributor);
        vm.expectRevert(abi.encodeWithSelector(BatchToken.NotPharmacy.selector, distributor));
        batch.dispense(id, keccak256("p"));
    }

    function testDispenseRevertsInWrongState() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        vm.expectRevert(
            abi.encodeWithSelector(BatchToken.InvalidState.selector, id, BatchToken.State.Created)
        );
        batch.dispense(id, keccak256("p"));
    }

    function testManufacturerRecallsBatch() public {
        uint256 id = _shipToPharmacy();
        bytes32 reason = keccak256("counterfeit-report");
        vm.expectEmit(true, true, false, true, address(batch));
        emit BatchRecalled(id, manufacturer, reason);
        vm.prank(manufacturer);
        batch.recall(id, reason);
        assertEq(uint256(batch.stateOf(id)), uint256(BatchToken.State.Recalled));
    }

    function testRegulatorRecallsBatch() public {
        uint256 id = _shipToPharmacy();
        vm.prank(regulator);
        batch.recall(id, keccak256("regulator-order"));
        assertEq(uint256(batch.stateOf(id)), uint256(BatchToken.State.Recalled));
    }

    function testOutsiderCannotRecall() public {
        uint256 id = _mintDefault();
        vm.prank(outsider);
        vm.expectRevert(abi.encodeWithSelector(BatchToken.NotManufacturer.selector, outsider));
        batch.recall(id, keccak256("x"));
    }

    function testRecallInTransitClearsPendingRecipient() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        batch.initiateCustody(id, distributor, CITY_KY);
        vm.prank(manufacturer);
        batch.recall(id, keccak256("x"));
        BatchToken.Batch memory b = batch.getBatch(id);
        assertEq(b.pendingRecipient, address(0));
        assertEq(uint256(b.state), uint256(BatchToken.State.Recalled));
    }

    function testDestroyRecalledBatch() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        batch.recall(id, keccak256("x"));
        vm.prank(manufacturer);
        batch.destroy(id);
        assertEq(uint256(batch.stateOf(id)), uint256(BatchToken.State.Destroyed));
    }

    function testDestroyRequiresRecall() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        vm.expectRevert(
            abi.encodeWithSelector(BatchToken.InvalidState.selector, id, BatchToken.State.Created)
        );
        batch.destroy(id);
    }

    function testOracleRecordsFlaggedAnomaly() public {
        uint256 id = _mintDefault();
        bytes32 model = keccak256("model-v1");
        bytes32 data = keccak256("features");
        vm.expectEmit(true, false, false, true, address(batch));
        emit AnomalyRecorded(id, 8_500, model, data, 2);
        vm.prank(oracle);
        batch.recordAnomaly(id, 8_500, model, data, 2);

        BatchToken.Batch memory b = batch.getBatch(id);
        assertTrue(b.flagged);
        assertEq(b.anomalyScore, 8_500);
        assertEq(b.modelVersion, model);
        assertEq(b.dataHash, data);
    }

    function testOracleScoreBelowThresholdIsNotFlagged() public {
        uint256 id = _mintDefault();
        vm.prank(oracle);
        batch.recordAnomaly(id, 6_999, keccak256("m"), keccak256("d"), 1);
        assertFalse(batch.getBatch(id).flagged);
    }

    function testRecordAnomalyOnlyOracle() public {
        uint256 id = _mintDefault();
        vm.prank(outsider);
        vm.expectRevert();
        batch.recordAnomaly(id, 9_000, keccak256("m"), keccak256("d"), 1);
    }

    function testRecordAnomalyRejectsScoreAboveMax() public {
        uint256 id = _mintDefault();
        vm.prank(oracle);
        vm.expectRevert(abi.encodeWithSelector(BatchToken.InvalidScore.selector, 10_001));
        batch.recordAnomaly(id, 10_001, keccak256("m"), keccak256("d"), 1);
    }

    function testSetOracleMovesRole() public {
        address next = makeAddr("nextOracle");
        batch.setOracle(next);
        assertEq(batch.oracle(), next);
        assertFalse(batch.hasRole(batch.ORACLE_ROLE(), oracle));
        assertTrue(batch.hasRole(batch.ORACLE_ROLE(), next));

        uint256 id = _mintDefault();
        vm.prank(oracle);
        vm.expectRevert();
        batch.recordAnomaly(id, 9_000, keccak256("m"), keccak256("d"), 1);

        vm.prank(next);
        batch.recordAnomaly(id, 9_000, keccak256("m"), keccak256("d"), 1);
        assertTrue(batch.getBatch(id).flagged);
    }

    function testSetOracleRejectsZeroAddress() public {
        vm.expectRevert(BatchToken.ZeroAddress.selector);
        batch.setOracle(address(0));
    }

    function testThresholdUpdateChangesFlag() public {
        uint256 id = _mintDefault();
        batch.setThresholdBps(9_000);
        assertEq(batch.thresholdBps(), 9_000);
        vm.prank(oracle);
        batch.recordAnomaly(id, 8_000, keccak256("m"), keccak256("d"), 1);
        assertFalse(batch.getBatch(id).flagged);
    }

    function testPauseBlocksMint() public {
        batch.pause();
        vm.prank(manufacturer);
        vm.expectRevert();
        batch.mint(PRODUCT, SERIAL, uint64(block.timestamp + 1 days), 10, META, CITY_KY);
        batch.unpause();
        _mintDefault();
    }

    function testGetBatchNotFound() public {
        vm.expectRevert(abi.encodeWithSelector(BatchToken.BatchNotFound.selector, 42));
        batch.getBatch(42);
    }

    function testGetBatchesPagination() public {
        _mintDefault();
        vm.prank(manufacturer);
        batch.mint(PRODUCT, 1002, uint64(block.timestamp + 365 days), 50, META, CITY_KY);

        BatchToken.BatchView[] memory page = batch.getBatches(0, 10);
        assertEq(page.length, 2);
        assertEq(page[0].id, 1);
        assertEq(page[1].id, 2);

        BatchToken.BatchView[] memory second = batch.getBatches(2, 1);
        assertEq(second.length, 1);
        assertEq(second[0].id, 2);

        BatchToken.BatchView[] memory emptyPage = batch.getBatches(5, 10);
        assertEq(emptyPage.length, 0);
    }

    function testOwnerOfUpdatesOnCustodyAccept() public {
        uint256 id = _shipToDistributor();
        assertEq(batch.ownerOf(id), distributor);
        vm.prank(distributor);
        batch.initiateCustody(id, pharmacy, CITY_LV);
        vm.prank(pharmacy);
        batch.acceptCustody(id);
        assertEq(batch.ownerOf(id), pharmacy);
    }

    function testConstructorRejectsZeroAdmin() public {
        vm.expectRevert(BatchToken.ZeroAddress.selector);
        new BatchToken(address(0), registry, oracle, 7_000);
    }

    function testConstructorRejectsZeroRegistry() public {
        vm.expectRevert(BatchToken.ZeroAddress.selector);
        new BatchToken(address(this), IParticipantRegistry(address(0)), oracle, 7_000);
    }

    function testConstructorRejectsHighThreshold() public {
        vm.expectRevert(abi.encodeWithSelector(BatchToken.InvalidThreshold.selector, 10_001));
        new BatchToken(address(this), registry, oracle, 10_001);
    }

    function testInitiateRevertsInTransit() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        batch.initiateCustody(id, distributor, CITY_KY);
        vm.prank(manufacturer);
        vm.expectRevert(
            abi.encodeWithSelector(BatchToken.InvalidState.selector, id, BatchToken.State.InTransit)
        );
        batch.initiateCustody(id, distributor, CITY_KY);
    }

    function testInitiateRejectsEmptyCity() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        vm.expectRevert(abi.encodeWithSelector(BatchToken.InvalidRecipient.selector, distributor));
        batch.initiateCustody(id, distributor, bytes2(0));
    }

    function testInitiateRejectsRegulator() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        vm.expectRevert(abi.encodeWithSelector(BatchToken.InvalidRecipient.selector, regulator));
        batch.initiateCustody(id, regulator, CITY_KY);
    }

    function testAcceptRevertsInWrongState() public {
        uint256 id = _mintDefault();
        vm.prank(distributor);
        vm.expectRevert(
            abi.encodeWithSelector(BatchToken.InvalidState.selector, id, BatchToken.State.Created)
        );
        batch.acceptCustody(id);
    }

    function testRejectRevertsInWrongState() public {
        uint256 id = _mintDefault();
        vm.prank(distributor);
        vm.expectRevert(
            abi.encodeWithSelector(BatchToken.InvalidState.selector, id, BatchToken.State.Created)
        );
        batch.rejectCustody(id);
    }

    function testRejectOnlyByPendingRecipient() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        batch.initiateCustody(id, distributor, CITY_KY);
        vm.prank(pharmacy);
        vm.expectRevert(
            abi.encodeWithSelector(BatchToken.NotPendingRecipient.selector, id, pharmacy)
        );
        batch.rejectCustody(id);
    }

    function testSplitRejectsZeroQuantity() public {
        uint256 id = _mintDefault();
        uint128[] memory parts = new uint128[](1);
        parts[0] = 0;
        vm.prank(manufacturer);
        vm.expectRevert(BatchToken.InvalidSplit.selector);
        batch.split(id, parts);
    }

    function testDispenseOnlyByCustodian() public {
        uint256 id = _shipToPharmacy();
        vm.prank(distributor);
        vm.expectRevert(abi.encodeWithSelector(BatchToken.NotCustodian.selector, id, distributor));
        batch.dispense(id, keccak256("p"));
    }

    function testDispenseRejectsEmptyCommitment() public {
        uint256 id = _shipToPharmacy();
        vm.prank(pharmacy);
        vm.expectRevert(BatchToken.InvalidQuantity.selector);
        batch.dispense(id, bytes32(0));
    }

    function testDestroyOnlyByCustodian() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        batch.recall(id, keccak256("x"));
        vm.prank(distributor);
        vm.expectRevert(abi.encodeWithSelector(BatchToken.NotCustodian.selector, id, distributor));
        batch.destroy(id);
    }

    function testThresholdRejectsAboveMax() public {
        vm.expectRevert(abi.encodeWithSelector(BatchToken.InvalidThreshold.selector, 10_001));
        batch.setThresholdBps(10_001);
    }

    function testGetBatchRejectsZeroId() public {
        vm.expectRevert(abi.encodeWithSelector(BatchToken.BatchNotFound.selector, 0));
        batch.getBatch(0);
    }

    function testRecallRejectsDestroyedBatch() public {
        uint256 id = _mintDefault();
        vm.startPrank(manufacturer);
        batch.recall(id, keccak256("x"));
        batch.destroy(id);
        vm.expectRevert(abi.encodeWithSelector(BatchToken.NotRecallable.selector, id));
        batch.recall(id, keccak256("x"));
        vm.stopPrank();
    }
}
