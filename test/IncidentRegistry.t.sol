// SPDX-License-Identifier: MIT
pragma solidity 0.8.28;

import {Fixture} from "./Fixture.sol";
import {BatchToken} from "../src/BatchToken.sol";
import {IncidentRegistry} from "../src/IncidentRegistry.sol";
import {IParticipantRegistry} from "../src/interfaces/IParticipantRegistry.sol";
import {IBatchToken} from "../src/interfaces/IBatchToken.sol";

contract IncidentRegistryTest is Fixture {
    bytes32 internal constant NOTE = keccak256("incident-note");

    event IncidentReported(
        uint256 indexed incidentId,
        uint256 indexed batchId,
        IncidentRegistry.IncidentKind kind,
        IncidentRegistry.Severity severity,
        address indexed reporter
    );
    event ModelDecisionRecorded(
        uint256 indexed incidentId, uint16 scoreBps, bytes32 modelVersion, bytes32 dataHash
    );
    event IncidentConfirmed(uint256 indexed incidentId, address indexed verifier);

    function _openIncident() internal returns (uint256 id) {
        uint256 batchId = _mintDefault();
        vm.prank(distributor);
        id = incidents.reportIncident(
            batchId,
            IncidentRegistry.IncidentKind.RouteAnomaly,
            IncidentRegistry.Severity.High,
            NOTE
        );
    }

    function testReportIncident() public {
        uint256 batchId = _mintDefault();
        vm.expectEmit(true, true, true, true, address(incidents));
        emit IncidentReported(
            1,
            batchId,
            IncidentRegistry.IncidentKind.RouteAnomaly,
            IncidentRegistry.Severity.High,
            distributor
        );
        vm.prank(distributor);
        uint256 id = incidents.reportIncident(
            batchId,
            IncidentRegistry.IncidentKind.RouteAnomaly,
            IncidentRegistry.Severity.High,
            NOTE
        );

        IncidentRegistry.Incident memory incident = incidents.getIncident(id);
        assertEq(incident.batchId, batchId);
        assertEq(uint256(incident.status), uint256(IncidentRegistry.Status.Open));
        assertEq(incident.reporter, distributor);
        assertEq(incident.noteHash, NOTE);
        assertEq(incidents.incidentCount(), 1);
    }

    function testReportRequiresParticipant() public {
        uint256 batchId = _mintDefault();
        vm.prank(outsider);
        vm.expectRevert(abi.encodeWithSelector(IncidentRegistry.NotParticipant.selector, outsider));
        incidents.reportIncident(
            batchId,
            IncidentRegistry.IncidentKind.Counterfeit,
            IncidentRegistry.Severity.Critical,
            NOTE
        );
    }

    function testReportRejectsInvalidKind() public {
        uint256 batchId = _mintDefault();
        vm.prank(distributor);
        vm.expectRevert(IncidentRegistry.InvalidKind.selector);
        incidents.reportIncident(
            batchId, IncidentRegistry.IncidentKind.None, IncidentRegistry.Severity.High, NOTE
        );
    }

    function testReportRejectsInvalidSeverity() public {
        uint256 batchId = _mintDefault();
        vm.prank(distributor);
        vm.expectRevert(IncidentRegistry.InvalidSeverity.selector);
        incidents.reportIncident(
            batchId, IncidentRegistry.IncidentKind.Counterfeit, IncidentRegistry.Severity.None, NOTE
        );
    }

    function testReportRejectsEmptyNote() public {
        uint256 batchId = _mintDefault();
        vm.prank(distributor);
        vm.expectRevert(IncidentRegistry.EmptyNote.selector);
        incidents.reportIncident(
            batchId,
            IncidentRegistry.IncidentKind.Counterfeit,
            IncidentRegistry.Severity.Low,
            bytes32(0)
        );
    }

    function testReportRejectsUnknownBatch() public {
        vm.prank(distributor);
        vm.expectRevert(abi.encodeWithSelector(IncidentRegistry.BatchNotFound.selector, 99));
        incidents.reportIncident(
            99, IncidentRegistry.IncidentKind.Counterfeit, IncidentRegistry.Severity.Low, NOTE
        );
    }

    function testOracleSubmitsDecision() public {
        uint256 id = _openIncident();
        bytes32 model = keccak256("model-v1");
        bytes32 data = keccak256("features-v1");
        vm.expectEmit(true, false, false, true, address(incidents));
        emit ModelDecisionRecorded(id, 9_100, model, data);
        vm.prank(oracle);
        incidents.submitModelDecision(id, 9_100, model, data);

        IncidentRegistry.Incident memory incident = incidents.getIncident(id);
        assertEq(uint256(incident.status), uint256(IncidentRegistry.Status.ModelReviewed));
        assertEq(incident.scoreBps, 9_100);
        assertEq(incident.modelVersion, model);
        assertEq(incident.dataHash, data);
    }

    function testDecisionOnlyByOracle() public {
        uint256 id = _openIncident();
        vm.prank(distributor);
        vm.expectRevert();
        incidents.submitModelDecision(id, 9_000, keccak256("m"), keccak256("d"));
    }

    function testDecisionCannotBeReplayed() public {
        uint256 id = _openIncident();
        vm.prank(oracle);
        incidents.submitModelDecision(id, 9_000, keccak256("m"), keccak256("d"));
        vm.prank(oracle);
        vm.expectRevert(
            abi.encodeWithSelector(
                IncidentRegistry.InvalidTransition.selector,
                id,
                IncidentRegistry.Status.ModelReviewed
            )
        );
        incidents.submitModelDecision(id, 9_000, keccak256("m"), keccak256("d"));
    }

    function testDecisionRejectsScoreAboveMax() public {
        uint256 id = _openIncident();
        vm.prank(oracle);
        vm.expectRevert(abi.encodeWithSelector(IncidentRegistry.InvalidScore.selector, 10_001));
        incidents.submitModelDecision(id, 10_001, keccak256("m"), keccak256("d"));
    }

    function testOracleIncidentStartsReviewed() public {
        uint256 batchId = _mintDefault();
        bytes32 model = keccak256("model-v1");
        bytes32 data = keccak256("features-v1");
        vm.prank(oracle);
        uint256 id = incidents.reportOracleIncident(
            batchId,
            IncidentRegistry.IncidentKind.Counterfeit,
            IncidentRegistry.Severity.Critical,
            9_800,
            model,
            data,
            NOTE
        );
        IncidentRegistry.Incident memory incident = incidents.getIncident(id);
        assertEq(uint256(incident.status), uint256(IncidentRegistry.Status.ModelReviewed));
        assertEq(incident.scoreBps, 9_800);
        assertEq(incident.modelVersion, model);
        assertEq(incident.dataHash, data);
    }

    function testOracleIncidentOnlyByOracle() public {
        uint256 batchId = _mintDefault();
        vm.prank(outsider);
        vm.expectRevert();
        incidents.reportOracleIncident(
            batchId,
            IncidentRegistry.IncidentKind.Counterfeit,
            IncidentRegistry.Severity.Critical,
            9_800,
            keccak256("m"),
            keccak256("d"),
            NOTE
        );
    }

    function testConfirmRecallsBatch() public {
        uint256 id = _openIncident();
        uint256 batchId = incidents.getIncident(id).batchId;
        vm.prank(oracle);
        incidents.submitModelDecision(id, 9_500, keccak256("m"), keccak256("d"));

        vm.expectEmit(true, true, false, false, address(incidents));
        emit IncidentConfirmed(id, verifier);
        vm.prank(verifier);
        incidents.confirmIncident(id);

        assertEq(
            uint256(incidents.getIncident(id).status), uint256(IncidentRegistry.Status.Confirmed)
        );
        assertEq(uint256(batch.stateOf(batchId)), uint256(BatchToken.State.Recalled));
    }

    function testConfirmAlreadyRecalledBatchSucceeds() public {
        uint256 id = _openIncident();
        uint256 batchId = incidents.getIncident(id).batchId;
        vm.prank(manufacturer);
        batch.recall(batchId, keccak256("manual"));
        vm.prank(oracle);
        incidents.submitModelDecision(id, 9_500, keccak256("m"), keccak256("d"));
        vm.prank(verifier);
        incidents.confirmIncident(id);
        assertEq(
            uint256(incidents.getIncident(id).status), uint256(IncidentRegistry.Status.Confirmed)
        );
    }

    function testConfirmOnlyByVerifier() public {
        uint256 id = _openIncident();
        vm.prank(oracle);
        incidents.submitModelDecision(id, 9_500, keccak256("m"), keccak256("d"));
        vm.prank(manufacturer);
        vm.expectRevert();
        incidents.confirmIncident(id);
    }

    function testConfirmRequiresReviewedStatus() public {
        uint256 id = _openIncident();
        vm.prank(verifier);
        vm.expectRevert(
            abi.encodeWithSelector(
                IncidentRegistry.InvalidTransition.selector, id, IncidentRegistry.Status.Open
            )
        );
        incidents.confirmIncident(id);
    }

    function testDismissIncident() public {
        uint256 id = _openIncident();
        vm.prank(oracle);
        incidents.submitModelDecision(id, 4_000, keccak256("m"), keccak256("d"));
        vm.prank(verifier);
        incidents.dismissIncident(id);
        assertEq(
            uint256(incidents.getIncident(id).status), uint256(IncidentRegistry.Status.Dismissed)
        );
    }

    function testResolveConfirmedIncident() public {
        uint256 id = _openIncident();
        vm.prank(oracle);
        incidents.submitModelDecision(id, 9_500, keccak256("m"), keccak256("d"));
        vm.prank(verifier);
        incidents.confirmIncident(id);
        vm.prank(verifier);
        incidents.resolveIncident(id);
        assertEq(
            uint256(incidents.getIncident(id).status), uint256(IncidentRegistry.Status.Resolved)
        );
    }

    function testResolveRequiresConfirmedStatus() public {
        uint256 id = _openIncident();
        vm.prank(verifier);
        vm.expectRevert(
            abi.encodeWithSelector(
                IncidentRegistry.InvalidTransition.selector, id, IncidentRegistry.Status.Open
            )
        );
        incidents.resolveIncident(id);
    }

    function testIncidentsByBatch() public {
        uint256 id = _openIncident();
        uint256 batchId = incidents.getIncident(id).batchId;
        vm.prank(oracle);
        incidents.reportOracleIncident(
            batchId,
            IncidentRegistry.IncidentKind.Counterfeit,
            IncidentRegistry.Severity.Critical,
            9_000,
            keccak256("m"),
            keccak256("d"),
            NOTE
        );
        uint256[] memory ids = incidents.incidentsByBatch(batchId);
        assertEq(ids.length, 2);
        assertEq(ids[0], 1);
        assertEq(ids[1], 2);
    }

    function testIncidentNotFound() public {
        vm.expectRevert(abi.encodeWithSelector(IncidentRegistry.IncidentNotFound.selector, 42));
        incidents.getIncident(42);
    }

    function testSetOracleMovesRole() public {
        address next = makeAddr("nextOracle");
        incidents.setOracle(next);
        assertEq(incidents.oracle(), next);
        assertFalse(incidents.hasRole(incidents.ORACLE_ROLE(), oracle));
        assertTrue(incidents.hasRole(incidents.ORACLE_ROLE(), next));
    }

    function testPauseBlocksReporting() public {
        uint256 batchId = _mintDefault();
        incidents.pause();
        vm.prank(distributor);
        vm.expectRevert();
        incidents.reportIncident(
            batchId, IncidentRegistry.IncidentKind.Counterfeit, IncidentRegistry.Severity.High, NOTE
        );
        incidents.unpause();
    }

    function testSeverityStored() public {
        uint256 id = _openIncident();
        assertEq(
            uint256(incidents.getIncident(id).severity), uint256(IncidentRegistry.Severity.High)
        );
    }

    function testConstructorRejectsZeroAdmin() public {
        vm.expectRevert(IncidentRegistry.ZeroAddress.selector);
        new IncidentRegistry(address(0), verifier, registry, IBatchToken(address(batch)), oracle);
    }

    function testConstructorRejectsZeroVerifier() public {
        vm.expectRevert(IncidentRegistry.ZeroAddress.selector);
        new IncidentRegistry(
            address(this), address(0), registry, IBatchToken(address(batch)), oracle
        );
    }

    function testConstructorRejectsZeroRegistry() public {
        vm.expectRevert(IncidentRegistry.ZeroAddress.selector);
        new IncidentRegistry(
            address(this),
            verifier,
            IParticipantRegistry(address(0)),
            IBatchToken(address(batch)),
            oracle
        );
    }

    function testConstructorRejectsZeroBatch() public {
        vm.expectRevert(IncidentRegistry.ZeroAddress.selector);
        new IncidentRegistry(address(this), verifier, registry, IBatchToken(address(0)), oracle);
    }

    function testOracleIncidentRejectsHighScore() public {
        uint256 batchId = _mintDefault();
        vm.prank(oracle);
        vm.expectRevert(abi.encodeWithSelector(IncidentRegistry.InvalidScore.selector, 10_001));
        incidents.reportOracleIncident(
            batchId,
            IncidentRegistry.IncidentKind.Counterfeit,
            IncidentRegistry.Severity.Critical,
            10_001,
            keccak256("m"),
            keccak256("d"),
            NOTE
        );
    }

    function testDismissRequiresReviewedStatus() public {
        uint256 id = _openIncident();
        vm.prank(verifier);
        vm.expectRevert(
            abi.encodeWithSelector(
                IncidentRegistry.InvalidTransition.selector, id, IncidentRegistry.Status.Open
            )
        );
        incidents.dismissIncident(id);
    }

    function testReportRejectsZeroBatch() public {
        vm.prank(distributor);
        vm.expectRevert(abi.encodeWithSelector(IncidentRegistry.BatchNotFound.selector, 0));
        incidents.reportIncident(
            0, IncidentRegistry.IncidentKind.Counterfeit, IncidentRegistry.Severity.Low, NOTE
        );
    }

    function testGetIncidentRejectsZeroId() public {
        vm.expectRevert(abi.encodeWithSelector(IncidentRegistry.IncidentNotFound.selector, 0));
        incidents.getIncident(0);
    }

    function testSetOracleRejectsZeroAddress() public {
        vm.expectRevert(IncidentRegistry.ZeroAddress.selector);
        incidents.setOracle(address(0));
    }
}

contract IntegrationTest is Fixture {
    bytes32 internal constant NOTE = keccak256("clone-detected");

    function testFullTraceabilityScenario() public {
        uint256 id = _mintDefault();
        assertEq(batch.verifySerial(PRODUCT, SERIAL), id);

        vm.prank(manufacturer);
        batch.initiateCustody(id, distributor, CITY_KY);
        vm.prank(distributor);
        batch.acceptCustody(id);
        vm.prank(distributor);
        batch.initiateCustody(id, pharmacy, CITY_LV);
        vm.prank(pharmacy);
        batch.acceptCustody(id);
        assertEq(batch.ownerOf(id), pharmacy);

        bytes32 model = keccak256("model-v1");
        bytes32 data = keccak256("features-clone");
        vm.prank(oracle);
        batch.recordAnomaly(id, 9_600, model, data, 3);

        vm.prank(oracle);
        uint256 incidentId = incidents.reportOracleIncident(
            id,
            IncidentRegistry.IncidentKind.Counterfeit,
            IncidentRegistry.Severity.Critical,
            9_600,
            model,
            data,
            NOTE
        );
        vm.prank(verifier);
        incidents.confirmIncident(incidentId);

        assertEq(uint256(batch.stateOf(id)), uint256(BatchToken.State.Recalled));
        assertEq(
            uint256(incidents.getIncident(incidentId).status),
            uint256(IncidentRegistry.Status.Confirmed)
        );

        vm.prank(verifier);
        incidents.resolveIncident(incidentId);
        assertEq(
            uint256(incidents.getIncident(incidentId).status),
            uint256(IncidentRegistry.Status.Resolved)
        );
    }

    function testSplitAndDistributeChildren() public {
        uint256 id = _mintDefault();
        uint128[] memory parts = new uint128[](2);
        parts[0] = 300;
        parts[1] = 700;
        vm.prank(manufacturer);
        uint256[] memory children = batch.split(id, parts);

        vm.prank(manufacturer);
        batch.initiateCustody(children[0], distributor, CITY_KY);
        vm.prank(distributor);
        batch.acceptCustody(children[0]);
        vm.prank(manufacturer);
        batch.initiateCustody(children[1], pharmacyTwo, CITY_LV);
        vm.prank(pharmacyTwo);
        batch.acceptCustody(children[1]);

        assertEq(batch.ownerOf(children[0]), distributor);
        assertEq(batch.ownerOf(children[1]), pharmacyTwo);
        assertEq(batch.getBatch(children[0]).parentId, id);
        assertEq(uint256(batch.stateOf(children[0])), uint256(BatchToken.State.Delivered));
    }

    function testDispensedBatchCanBeRecalled() public {
        uint256 id = _shipToPharmacy();
        vm.prank(pharmacy);
        batch.dispense(id, keccak256("patient"));
        vm.prank(manufacturer);
        batch.recall(id, keccak256("adverse-event"));
        assertEq(uint256(batch.stateOf(id)), uint256(BatchToken.State.Recalled));
    }

    function testSuspendedDistributorCannotAccept() public {
        uint256 id = _mintDefault();
        vm.prank(manufacturer);
        batch.initiateCustody(id, distributor, CITY_KY);
        vm.prank(verifier);
        registry.suspend(distributor);
        vm.prank(distributor);
        vm.expectRevert(abi.encodeWithSelector(BatchToken.InvalidRecipient.selector, distributor));
        batch.acceptCustody(id);
        assertEq(batch.ownerOf(id), manufacturer);
        assertEq(uint256(batch.stateOf(id)), uint256(BatchToken.State.InTransit));
    }
}
